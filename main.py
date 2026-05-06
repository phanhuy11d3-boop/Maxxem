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
from typing import Tuple

from groq import Groq

from storage.postgres import (
    init_db, upsert_article, get_unprocessed, mark_processed, increment_retry,
    mark_tg_sent, get_tg_failed,
)
from scrapers.generic_rss import scrape_all_feeds
from processors.insight_extractor import get_groq_client, triage_articles, analyze_articles_batch
from models.article import MarketImpact
from utils.notifier import send_telegram, send_heartbeat

# Cấu hình logging tập trung một lần duy nhất — tất cả module con kế thừa qua getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Kích thước mỗi lần gọi Groq API (rate-limit safe). Pipeline sẽ lặp qua toàn bộ backlog.
MAX_BATCH_SIZE = 20

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


def _process_chunk(
    chunk: list, groq_client: Groq
) -> Tuple[int, int, int]:
    """
    Xử lý một chunk bài qua Triage → Batch Analysis → Telegram.
    Trả về (ai_processed, llm_errors, tg_errors) cho chunk này.
    """
    ai_processed = 0
    llm_errors = 0
    tg_errors = 0

    logger.info(f"   -> Triage {len(chunk)} bài...")
    triage_results = triage_articles(chunk, groq_client)
    n_triage = min(len(triage_results), len(chunk))

    if len(triage_results) != len(chunk):
        logger.warning(
            "Độ dài triage (%s) ≠ chunk (%s); %s bài cuối fallback high-impact.",
            len(triage_results), len(chunk), len(chunk) - n_triage,
        )

    high_impact = []
    for i in range(n_triage):
        article = chunk[i]
        if triage_results[i]:
            high_impact.append(article)
        else:
            mark_processed(
                article.id, 0.0, MarketImpact.NEUTRAL,
                "Routine news - skipped deep analysis.",
            )
            ai_processed += 1

    # Bài thiếu nhãn triage → fallback coi như high-impact
    for i in range(n_triage, len(chunk)):
        high_impact.append(chunk[i])

    low_skip = sum(1 for i in range(n_triage) if not triage_results[i])
    logger.info(
        f"   -> Triage xong: {len(high_impact)} high-impact | {low_skip} low-impact đã đóng."
    )

    if not high_impact:
        return ai_processed, llm_errors, tg_errors

    success = analyze_articles_batch(high_impact, groq_client)
    if not success:
        llm_errors += len(high_impact)
        logger.error("Batch analysis failed cho chunk.")
        for article in high_impact:
            increment_retry(article.id)
        return ai_processed, llm_errors, tg_errors

    for article in high_impact:
        if not article.processed:
            llm_errors += 1
            increment_retry(article.id)
            logger.warning("LLM thiếu kết quả cho id=%s, tăng retry.", article.id[:12])
            continue

        # Luôn mark_processed ngay sau LLM — tránh retry vô tận dù TG sau đó có fail
        mark_processed(
            article_id=article.id,
            sentiment=article.sentiment,
            market_impact=article.market_impact or MarketImpact.NEUTRAL,
            key_takeaway=article.key_takeaway,
            narrative_tag=article.narrative_tag,
            affected_tokens=article.affected_tokens,
            urgency=article.urgency,
        )
        ai_processed += 1

        if article.is_actionable:
            sent = send_telegram(article)
            mark_tg_sent(article.id, sent)  # ghi kết quả TG để có thể retry sau
            if not sent:
                tg_errors += 1
                logger.warning(f"Telegram fail cho {article.id[:12]} — sẽ retry lần chạy sau.")

    return ai_processed, llm_errors, tg_errors


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

    # Phase 1: init_db — nếu fail, gửi heartbeat ngay và thoát
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Không thể khởi tạo DB. Dừng pipeline: {e}")
        send_heartbeat(
            scraped=0, new=0, ai_processed=0,
            db_errors=1, llm_errors=0, tg_errors=0,
            duration_s=time.monotonic() - start_time,
        )
        return

    # Phase 2-7: mọi lỗi không mong đợi đều được bắt; finally đảm bảo heartbeat luôn gửi
    try:
        # Phase 2: Retry Telegram-failed articles từ lần chạy trước
        tg_failed = get_tg_failed()
        if tg_failed:
            logger.info(f"2. Retry {len(tg_failed)} bài TG-failed từ lần chạy trước...")
            for article in tg_failed:
                sent = send_telegram(article)
                mark_tg_sent(article.id, sent)
                if not sent:
                    tg_errors += 1

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
        total_unprocessed = len(unprocessed)
        logger.info(
            f"5. Queue unprocessed: {total_unprocessed} bài. "
            f"Xử lý theo chunks {MAX_BATCH_SIZE}..."
        )

        if not unprocessed:
            logger.info("Không có bài báo nào cần xử lý AI.")
        else:
            groq_client = get_groq_client()
            if not groq_client:
                logger.error("Không thể khởi tạo Groq client. Bỏ qua phase AI.")
                llm_errors += total_unprocessed
                for article in unprocessed:
                    increment_retry(article.id)
            else:
                num_chunks = (total_unprocessed + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
                for idx, chunk_start in enumerate(range(0, total_unprocessed, MAX_BATCH_SIZE), 1):
                    chunk = unprocessed[chunk_start:chunk_start + MAX_BATCH_SIZE]
                    logger.info(f"   Chunk {idx}/{num_chunks} ({len(chunk)} bài)...")
                    c_ai, c_llm, c_tg = _process_chunk(chunk, groq_client)
                    ai_processed += c_ai
                    llm_errors += c_llm
                    tg_errors += c_tg

    except Exception as e:
        logger.critical(f"Pipeline crash không mong đợi: {e}", exc_info=True)
        db_errors += 1

    finally:
        # Luôn chạy — kể cả khi crash ở bất kỳ bước nào trên
        duration = time.monotonic() - start_time
        logger.info(
            f"=== Pipeline Hoàn Tất | "
            f"Mới: {new_count} | AI: {ai_processed} | "
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
            "=== Agentic Hoàn Tất | Mới: %s | AI: %s | Lỗi DB/LLM/TG: %s/%s/%s | Cảnh báo: %s | %.1fs ===",
            stats.new_count,
            stats.ai_processed,
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
