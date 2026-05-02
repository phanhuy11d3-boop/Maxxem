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

from storage.postgres import init_db, upsert_article, get_unprocessed, mark_processed, increment_retry
from scrapers.generic_rss import scrape_all_feeds
from processors.insight_extractor import get_groq_client, analyze_article
from utils.notifier import send_telegram, send_heartbeat

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Giới hạn số bài xử lý AI mỗi lần chạy để đảm bảo không dính rate limit nếu tích tụ backlog quá lớn
MAX_BATCH_SIZE = 20

def main():
    start_time = time.monotonic()
    logger.info("=== Bắt đầu chạy pipeline CryptoSentinel ===")

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
    logger.info(f"4. Bắt đầu xử lý AI (FinOps Batch Limit). Tổng cần xử lý: {len(unprocessed)}, Lấy ra: {len(batch)}")

    if batch:
        groq_client = get_groq_client()
        if not groq_client:
            logger.error("Dừng phase AI vì không thể khởi tạo Groq client (thiếu API Key).")
            llm_errors += 1
        else:
            # 5. Phân tích & Gửi thông báo
            ai_processed = 0
            for article in batch:
                success = analyze_article(article, groq_client)
                if success:
                    mark_processed(
                        article_id=article.id,
                        sentiment=article.sentiment,
                        market_impact=article.market_impact,
                        key_takeaway=article.key_takeaway
                    )
                    ai_processed += 1
                    article.processed = True

                    # Gửi Telegram (bên trong hàm đã check is_actionable)
                    sent = send_telegram(article)
                    if not sent and article.is_actionable:
                        # Chỉ đếm lỗi nếu bài ĐÁNG GỬI mà không gửi được
                        tg_errors += 1
                else:
                    logger.warning(f"Phân tích thất bại bài {article.id[:12]}... Tăng retry_count.")
                    increment_retry(article.id)
                    llm_errors += 1
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


if __name__ == "__main__":
    main()
