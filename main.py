"""
main.py
=======
Nhạc trưởng điều phối toàn bộ luồng chạy của CryptoSentinel.
Kết nối 4 Phase: Scraper (Lấy tin) -> Storage (Lưu trữ/Dedup) -> AI (Phân tích) -> Telegram (Báo cáo).

Cải tiến v2.2:
  - Theo dõi error counters (db_errors, llm_errors, tg_errors) cho từng giai đoạn.
  - Gửi Heartbeat tổng kết pipeline qua Telegram sau mỗi lần chạy.
  - Đo thời gian chạy toàn bộ pipeline (duration).
"""

import time
import logging
import argparse

from storage.postgres import init_db, upsert_article, get_unprocessed, mark_processed, increment_retry
from scrapers.generic_rss import scrape_all_feeds
from processors.insight_extractor import get_groq_client, triage_articles, analyze_articles_batch
from models.article import MarketImpact
from utils.notifier import send_telegram, send_heartbeat

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Giới hạn số bài xử lý AI mỗi lần chạy để đảm bảo không dính rate limit nếu tích tụ backlog quá lớn
MAX_BATCH_SIZE = 20

def run_legacy_pipeline():
    """Luồng xử lý tuyến tính truyền thống (Linear Pipeline v2.2)"""
    start_time = time.monotonic()
    logger.info("=== Bắt đầu chạy LEGACY pipeline CryptoSentinel ===")

    # --- Error counters (Observability) ---
    db_errors = 0
    llm_errors = 0
    tg_errors = 0

    # 1. Khởi tạo Database (Supabase PostgreSQL)
    logger.info("1. Đang khởi tạo/kiểm tra cấu trúc Database...")
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Không thể khởi tạo DB. Dừng pipeline: {e}")
        # Heartbeat lỗi chí mạng — DB không lên được thì không làm gì được
        send_heartbeat(
            scraped=0, new=0, ai_processed=0,
            db_errors=1, llm_errors=0, tg_errors=0,
            duration_s=time.monotonic() - start_time
        )
        return

    # 2. Cào tin từ RSS
    logger.info("2. Đang cào tin tức từ các nguồn RSS...")
    articles = scrape_all_feeds()

    # 3. Lọc trùng & Lưu DB (ON CONFLICT DO NOTHING)
    logger.info(f"3. Lưu vào Database (Deduplication)... Tổng bài kéo về: {len(articles)}")
    new_count = 0
    for article in articles:
        result = upsert_article(article)
        if result is None:   # upsert trả None khi có DB error
            db_errors += 1
        elif result:
            new_count += 1
    logger.info(f"   -> Phát hiện {new_count} bài báo hoàn toàn mới.")

    # 4. Lấy danh sách cần phân tích AI
    unprocessed = get_unprocessed()
    batch = unprocessed[:MAX_BATCH_SIZE]
    logger.info(f"4. Bắt đầu xử lý AI (Token FinOps Batch). Tổng cần: {len(unprocessed)}, Lấy ra: {len(batch)}")

    if batch:
        ai_processed = 0
        groq_client = get_groq_client()
        if not groq_client:
            logger.error("Dừng phase AI vì không thể khởi tạo Groq client.")
            llm_errors += len(batch)
            for article in batch:
                increment_retry(article.id)
        else:
            logger.info(f"   -> Đang chạy Triage cho {len(batch)} bài báo...")
            triage_results = triage_articles(batch, groq_client)
            n_triage = min(len(triage_results), len(batch))
            if len(triage_results) != len(batch):
                logger.warning(
                    "Độ dài triage (%s) ≠ batch (%s); dùng %s nhãn đầu + fallback high-impact.",
                    len(triage_results),
                    len(batch),
                    n_triage,
                )
            triage_fallback = len(batch) - n_triage

            high_impact_batch = []

            for i in range(n_triage):
                article = batch[i]
                if triage_results[i]:
                    high_impact_batch.append(article)
                else:
                    mark_processed(
                        article.id,
                        0.0,
                        MarketImpact.NEUTRAL,
                        "Routine news - skipped deep analysis.",
                    )
                    ai_processed += 1

            for i in range(n_triage, len(batch)):
                high_impact_batch.append(batch[i])
            if triage_fallback:
                logger.warning(
                    "%s bài thiếu nhãn triage (độ dài response); coi như high-impact.",
                    triage_fallback,
                )

            low_skip = sum(1 for i in range(n_triage) if not triage_results[i])
            logger.info(
                f"   -> Triage xong: {len(high_impact_batch)} tin cần phân tích sâu | "
                f"{low_skip} low-impact đã đóng | "
                f"{triage_fallback} bài fallback (thiếu nhãn triage)."
            )

            if high_impact_batch:
                success = analyze_articles_batch(high_impact_batch, groq_client)
                if not success:
                    llm_errors += len(high_impact_batch)
                    logger.error("Batch analysis failed.")
                    for article in high_impact_batch:
                        increment_retry(article.id)
                else:
                    for article in high_impact_batch:
                        if not article.processed:
                            llm_errors += 1
                            increment_retry(article.id)
                            logger.warning(
                                "LLM thiếu kết quả cho id=%s..., tăng retry.",
                                article.id[:12],
                            )
                            continue
                        sent = send_telegram(article)
                        if not sent and article.is_actionable:
                            tg_errors += 1
                            logger.warning(f"Telegram fail cho {article.id[:12]}.")
                        else:
                            mark_processed(
                                article_id=article.id,
                                sentiment=article.sentiment,
                                market_impact=article.market_impact
                                or MarketImpact.NEUTRAL,
                                key_takeaway=article.key_takeaway,
                            )
                            ai_processed += 1
    else:
        ai_processed = 0
        logger.info("Không có bài báo nào cần xử lý.")

    duration = time.monotonic() - start_time
    logger.info(
        f"=== Pipeline Hoàn Tất | "
        f"Mới: {new_count} | AI: {ai_processed} | "
        f"Lỗi DB/LLM/TG: {db_errors}/{llm_errors}/{tg_errors} | "
        f"Thời gian: {duration:.1f}s ==="
    )

    # 6. Gửi Heartbeat tổng kết (luôn chạy dù có lỗi hay không)
    send_heartbeat(
        scraped=len(articles),
        new=new_count,
        ai_processed=ai_processed,
        db_errors=db_errors,
        llm_errors=llm_errors,
        tg_errors=tg_errors,
        duration_s=duration
    )


def main():
    parser = argparse.ArgumentParser(description="CryptoSentinel Orchestrator")
    parser.add_argument("--legacy", action="store_true", help="Chạy luồng tuyến tính cũ (v2.2)")
    parser.add_argument(
        "--agentic",
        action="store_true",
        help="In chú thích multi-agent roadmap; pipeline runtime vẫn là luồng tuyến tính (xem README).",
    )
    args = parser.parse_args()

    if args.agentic:
        logger.info("=== Flag --agentic: pipeline Python không đổi; roadmap agent ngoài Cursor/Claude ===")
        print(
            "\n[INFO] CryptoSentinel trên máy chỉ chạy main.py luồng RSS→Postgres→Groq→Telegram.\n"
            "[INFO] Scout/Analyst/Auditor/Broadcaster trong .claude/agents/ là playbook cho Cursor/Claude, "
            "chưa được gọi tự động tại đây.\n"
        )
        run_legacy_pipeline()
    else:
        run_legacy_pipeline()

if __name__ == "__main__":
    main()
