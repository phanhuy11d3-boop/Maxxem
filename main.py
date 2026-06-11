"""
main.py
=======
Nhạc trưởng điều phối toàn bộ luồng chạy của CryptoSentinel.
Kết nối 4 Phase: Scraper (Lấy tin) -> Storage (Lưu trữ/Dedup) -> AI (Phân tích) -> Telegram (Báo cáo).

Cải tiến v2.3:
  - FIX: Heartbeat luôn gửi dù pipeline crash ở bất kỳ bước nào (try...finally).
  - FIX: Xử lý toàn bộ backlog theo chunks — không còn cắt cứng 20 bài/lần.
  - FIX: Retry Telegram cho bài bị TG-fail (tg_sent=FALSE) ở lần chạy tiếp theo.
  - FIX: logging.basicConfig chỉ cấu hình một lần tại đây; các module dùng getLogger(__name__).
"""

import time
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from openai import OpenAI

from storage.postgres import (
    init_db, upsert_article, get_unprocessed, mark_processed_with_tg,
    increment_retry, get_tg_dispatch_queue, mark_tg_attempt, expire_stale_tg_queue,
    get_outbox_kpis,
)
from scrapers.generic_rss import scrape_all_feeds
from processors.insight_extractor import (
    get_llm_client, triage_articles, analyze_articles_batch, BatchOutcome,
)
from models.article import MarketImpact
from utils.notifier import send_telegram, send_heartbeat, send_admin_alert

# Cấu hình logging tập trung một lần duy nhất — tất cả module con kế thừa qua getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Kích thước mỗi lần gọi LLM API (rate-limit safe). Pipeline sẽ lặp qua toàn bộ backlog.
MAX_BATCH_SIZE = 20
LOW_CONF_SENTIMENT_ABS_THRESHOLD = 0.25
FAST_SIGNAL_SOURCES = {"Watcher.Guru", "Lookonchain", "UnusualWhales", "Arkham Alerts"}
TIER1_SOURCES = {
    "Blockworks", "CoinDesk", "Cointelegraph", "Unchained Crypto",
    "CryptoSlate", "SEC Press Releases",
    *FAST_SIGNAL_SOURCES,
}

STATE_FILE = Path(__file__).parent / "storage" / "state.json"


def _update_state(db_errors: int, llm_errors: int, tg_errors: int) -> None:
    """Ghi trạng thái pipeline vào state.json sau mỗi lần chạy."""
    try:
        current = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
        current.update({
            "last_run": datetime.now(timezone.utc).isoformat(),
            "current_phase": "idle",
            "system_status": "degraded" if (db_errors + llm_errors + tg_errors) > 0 else "healthy",
            "errors": {"db": db_errors, "llm": llm_errors, "telegram": tg_errors},
        })
        STATE_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Không thể ghi state.json: {e}")


def _dispatch_tg_queue(max_attempts: int = 3) -> Tuple[int, int, int]:
    """
    Outbox dispatcher:
      - expire stale (>30 phút) trước khi gửi
      - gửi queue pending/failed còn giá trị
      - retry tối đa max_attempts cho mỗi bài

    Returns: (actionable_count, sent_ok_count, tg_errors_count)
    """
    actionable = 0
    sent_ok = 0
    tg_errors = 0

    expired = expire_stale_tg_queue(max_age_minutes=30)
    if expired:
        logger.warning("Outbox expired stale actionable: %s bài.", expired)
        send_admin_alert(f"⏭️ <b>TG_EXPIRED</b>\nExpired stale actionable: {expired}")

    queue = get_tg_dispatch_queue(max_age_minutes=30, max_attempts=max_attempts)
    if not queue:
        return actionable, sent_ok, tg_errors

    logger.info("Dispatch TG queue: %s bài pending/failed.", len(queue))
    for article in queue:
        actionable += 1
        sent = send_telegram(article)
        mark_tg_attempt(article.id, success=sent, error=None if sent else "send_failed")
        if sent:
            sent_ok += 1
        else:
            tg_errors += 1
    return actionable, sent_ok, tg_errors


def _process_chunk(
    chunk: list, llm_client: OpenAI
) -> Tuple[int, int, int, int, int]:
    """
    Xử lý một chunk bài qua Triage → Batch Analysis → Telegram.
    Trả về (ai_processed, llm_errors, tg_errors, actionable, tg_sent_ok) cho chunk này.
    """
    ai_processed = 0
    llm_errors = 0
    tg_errors = 0
    actionable = 0
    tg_sent_ok = 0

    tier1 = [a for a in chunk if a.source in TIER1_SOURCES]
    tier2 = [a for a in chunk if a.source not in TIER1_SOURCES]
    low_conf_ids: set[str] = set()

    # Tier-1 luôn vào 70B (anti-miss). Triage 8B chỉ áp dụng cho Tier-2.
    high_impact = list(tier1)
    if tier2:
        logger.info("   -> Triage %s bài Tier-2...", len(tier2))
        triage_map = triage_articles(tier2, llm_client)  # Dict[id -> bool]
        for article in tier2:
            high_impact.append(article)
            if not triage_map.get(article.id, True):
                low_conf_ids.add(article.id)
    logger.info(
        "   -> Queue chunk: tier1=%s | tier2=%s | low_conf_candidates=%s",
        len(tier1), len(tier2), len(low_conf_ids),
    )

    outcome, missing = analyze_articles_batch(high_impact, llm_client)

    if outcome == BatchOutcome.STRUCTURAL_FAIL:
        # JSON malformed / contract vi phạm — retry vô ích, chỉ lãng phí token.
        # KHÔNG tăng retry_count (tránh chôn vĩnh viễn). Báo admin để fix prompt.
        llm_errors += len(high_impact)
        logger.error("Batch STRUCTURAL_FAIL — không tăng retry, alert admin.")
        send_admin_alert(
            "🚨 <b>LLM_STRUCTURAL_FAIL</b>\n"
            f"Chunk size={len(high_impact)}. Prompt/contract cần xem lại."
        )
        return ai_processed, llm_errors, tg_errors, actionable, tg_sent_ok

    if outcome == BatchOutcome.TRANSIENT_FAIL:
        # Rate limit / network — đáng retry. Tăng retry nhưng <= MAX_RETRY,
        # cron 1 phút đảm bảo bài vẫn còn trong cửa sổ live.
        llm_errors += len(high_impact)
        logger.warning("Batch TRANSIENT_FAIL — tăng retry, sẽ thử lại lần sau.")
        send_admin_alert(
            f"⚠️ <b>LLM_TRANSIENT_FAIL</b>\nChunk size={len(high_impact)}"
        )
        for article in high_impact:
            increment_retry(article.id)
        return ai_processed, llm_errors, tg_errors, actionable, tg_sent_ok

    # outcome == OK
    for article in high_impact:
        # Vector 3b: bài "missing" đã được analyze_articles_batch đánh dấu
        # processed=True + low_confidence=True + neutral. Caller chỉ ghi DB,
        # KHÔNG tăng retry_count cho bài bị LLM bỏ quên.
        article.low_confidence = bool(getattr(article, "low_confidence", False)) or (
            article.id in low_conf_ids
            or (
                article.sentiment is not None
                and abs(article.sentiment) < LOW_CONF_SENTIMENT_ABS_THRESHOLD
            )
        )

        # Phase 1 outbox state machine:
        #   - actionable -> enqueue pending
        #   - neutral    -> no tg state
        # Gửi thực tế do _dispatch_tg_queue() xử lý để kiểm soát retry/expiry tập trung.
        tg_outcome: Optional[bool] = None
        tg_status: Optional[str] = None
        tg_attempts: Optional[int] = None
        if article.is_actionable:
            actionable += 1
            tg_status = "pending"
            tg_outcome = None
            tg_attempts = 0

        mark_processed_with_tg(
            article_id=article.id,
            sentiment=article.sentiment,
            market_impact=article.market_impact or MarketImpact.NEUTRAL,
            key_takeaway=article.key_takeaway,
            narrative_tag=article.narrative_tag,
            affected_tokens=article.affected_tokens,
            urgency=article.urgency,
            low_confidence=article.low_confidence,
            tg_sent=tg_outcome,
            tg_status=tg_status,
            tg_attempts=tg_attempts,
        )
        ai_processed += 1

    if missing:
        send_admin_alert(
            f"⚠️ <b>LLM_MISSING_RESULTS</b>\n"
            f"{len(missing)}/{len(high_impact)} bài bị 70B bỏ quên — đã đóng low_conf."
        )

    return ai_processed, llm_errors, tg_errors, actionable, tg_sent_ok


def run_legacy_pipeline() -> None:
    """Luồng xử lý tuyến tính v2.3 — heartbeat được đảm bảo bởi try...finally."""
    start_time = time.monotonic()
    logger.info("=== Bắt đầu chạy pipeline CryptoSentinel v2.3 ===")

    db_errors = 0
    llm_errors = 0
    tg_errors = 0
    scraped_count = 0
    new_count = 0
    ai_processed = 0
    actionable_total = 0
    tg_sent_ok_total = 0

    # Phase 1: init_db — nếu fail, gửi heartbeat ngay và thoát
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Không thể khởi tạo DB. Dừng pipeline: {e}")
        send_admin_alert(f"🚨 <b>PIPELINE_INIT_DB_FAIL</b>\n{e!s}")
        send_heartbeat(
            scraped=0, new=0, ai_processed=0,
            db_errors=1, llm_errors=0, tg_errors=0,
            duration_s=time.monotonic() - start_time,
        )
        return

    # Phase 2-7: mọi lỗi không mong đợi đều được bắt; finally đảm bảo heartbeat luôn gửi
    try:
        # Phase 2: Dispatch queue cũ (pending/failed) trước khi ingest mới
        c_act, c_ok, c_tg = _dispatch_tg_queue(max_attempts=3)
        actionable_total += c_act
        tg_sent_ok_total += c_ok
        tg_errors += c_tg

        # Phase 3: Cào tin từ RSS
        logger.info("3. Đang cào tin tức từ các nguồn RSS...")
        articles = scrape_all_feeds()
        scraped_count = len(articles)

        # Phase 4: Dedup + Lưu DB
        logger.info(f"4. Deduplication... Tổng scraped: {scraped_count}")
        for article in articles:
            result = upsert_article(article)
            if result is None:
                db_errors += 1
            elif result:
                new_count += 1
        logger.info(f"   -> {new_count} bài mới.")

        # Phase 5: AI processing — xử lý TOÀN BỘ queue theo chunks MAX_BATCH_SIZE
        unprocessed = get_unprocessed()
        unprocessed.sort(
            key=lambda a: (
                0 if a.source in TIER1_SOURCES else 1,
                -a.scraped_at.timestamp(),
            )
        )
        total_unprocessed = len(unprocessed)
        logger.info(
            f"5. Queue unprocessed: {total_unprocessed} bài. "
            f"Xử lý theo chunks {MAX_BATCH_SIZE}..."
        )

        if not unprocessed:
            logger.info("Không có bài báo nào cần xử lý AI.")
        else:
            llm_client = get_llm_client()
            if not llm_client:
                logger.error("Không thể khởi tạo LLM client. Bỏ qua phase AI.")
                llm_errors += total_unprocessed
                for article in unprocessed:
                    increment_retry(article.id)
            else:
                num_chunks = (total_unprocessed + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
                for idx, chunk_start in enumerate(range(0, total_unprocessed, MAX_BATCH_SIZE), 1):
                    chunk = unprocessed[chunk_start:chunk_start + MAX_BATCH_SIZE]
                    logger.info(f"   Chunk {idx}/{num_chunks} ({len(chunk)} bài)...")
                    c_ai, c_llm, c_tg, c_act, c_ok = _process_chunk(chunk, llm_client)
                    ai_processed += c_ai
                    llm_errors += c_llm
                    tg_errors += c_tg
                    actionable_total += c_act
                    tg_sent_ok_total += c_ok

        # Phase 6: Dispatch các actionable vừa enqueue trong run hiện tại
        c_act, c_ok, c_tg = _dispatch_tg_queue(max_attempts=3)
        actionable_total += c_act
        tg_sent_ok_total += c_ok
        tg_errors += c_tg

    except Exception as e:
        logger.critical(f"Pipeline crash không mong đợi: {e}", exc_info=True)
        send_admin_alert(f"🚨 <b>PIPELINE_CRASH</b>\n{e!s}")
        db_errors += 1

    finally:
        # Luôn chạy — kể cả khi crash ở bất kỳ bước nào trên
        duration = time.monotonic() - start_time
        kpi = get_outbox_kpis(max_age_minutes=30)
        logger.info(
            f"=== Pipeline Hoàn Tất | "
            f"Mới: {new_count} | AI: {ai_processed} | "
            f"Actionable: {actionable_total} | TG OK: {tg_sent_ok_total} | "
            f"Lỗi DB/LLM/TG: {db_errors}/{llm_errors}/{tg_errors} | "
            f"Thời gian: {duration:.1f}s ==="
        )
        send_heartbeat(
            scraped=scraped_count,
            new=new_count,
            ai_processed=ai_processed,
            db_errors=db_errors,
            llm_errors=llm_errors,
            tg_errors=tg_errors,
            duration_s=duration,
            actionable=actionable_total,
            tg_sent_ok=tg_sent_ok_total,
            pending_count=kpi["pending_count"],
            failed_count=kpi["failed_count"],
            expired_count_60m=kpi["expired_count_60m"],
            oldest_pending_age_min=kpi["oldest_pending_age_min"],
        )
        _update_state(db_errors=db_errors, llm_errors=llm_errors, tg_errors=tg_errors)


def run_agentic_with_legacy_fallback() -> None:
    """
    Luồng agentic opt-in, có fallback về legacy.

    Không import agentic_runtime ở top-level để pipeline legacy mặc định không bị
    ảnh hưởng nếu runtime agentic đang được chỉnh sửa hoặc thiếu dependency.
    """
    start_time = time.monotonic()
    logger.info("=== Bắt đầu chạy Agentic Runtime opt-in ===")
    try:
        from agentic_runtime import run_agentic_pipeline

        stats = run_agentic_pipeline(max_batch_size=MAX_BATCH_SIZE)
        duration = time.monotonic() - start_time
        logger.info(
            "=== Agentic Hoàn Tất | Mới: %s | AI: %s | Actionable: %s | TG OK: %s | "
            "Lỗi DB/LLM/TG: %s/%s/%s | Cảnh báo: %s | %.1fs ===",
            stats.new_count,
            stats.ai_processed,
            stats.actionable,
            stats.tg_sent_ok,
            stats.db_errors,
            stats.llm_errors,
            stats.tg_errors,
            stats.warnings,
            duration,
        )
        send_heartbeat(
            scraped=stats.scraped_count,
            new=stats.new_count,
            ai_processed=stats.ai_processed,
            db_errors=stats.db_errors,
            llm_errors=stats.llm_errors,
            tg_errors=stats.tg_errors,
            duration_s=duration,
            actionable=stats.actionable,
            tg_sent_ok=stats.tg_sent_ok,
        )
        _update_state(
            db_errors=stats.db_errors,
            llm_errors=stats.llm_errors,
            tg_errors=stats.tg_errors,
        )
    except Exception as e:
        logger.critical(
            "Agentic pipeline lỗi nghiêm trọng: %s | Fallback về legacy pipeline để đảm bảo cadence.",
            e,
            exc_info=True,
        )
        send_admin_alert(f"🚨 <b>AGENTIC_FAIL_FALLBACK</b>\n{e!s}")
        run_legacy_pipeline()


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoSentinel Orchestrator")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--legacy",
        action="store_true",
        help="Run the stable linear pipeline. This is also the default.",
    )
    mode.add_argument(
        "--agentic",
        action="store_true",
        help="Run the guarded agentic runtime with automatic legacy fallback.",
    )
    args = parser.parse_args()

    if args.agentic:
        logger.info("Flag --agentic được bật: chạy Agentic Runtime với fallback legacy.")
        run_agentic_with_legacy_fallback()
        return

    logger.info("Mặc định chạy legacy pipeline ổn định.")
    run_legacy_pipeline()


if __name__ == "__main__":
    main()
