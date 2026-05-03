"""
storage/postgres.py
===================
Storage Engine của CryptoSentinel (v2.2 — Supabase PostgreSQL, Production-grade).

Thay đổi từ v2.1 (sqlite.py):
  - ĐỔI TÊN: sqlite.py → postgres.py (đúng Single Responsibility, không gây nhầm lẫn).
  - FIX DATA TYPES: TEXT timestamps → TIMESTAMPTZ, INTEGER boolean → BOOLEAN.
  - FIX CONNECTION PATTERN: Mở/đóng per-call → SimpleConnectionPool (tái sử dụng kết nối).
  - FIX ERROR HANDLING: Thêm try/except psycopg2.OperationalError cho toàn bộ DB ops.

Triết lý thiết kế (giữ nguyên):
  1. FinOps (Token Management): get_unprocessed() chặn gọi AI cho tin cũ.
  2. Deduplication (Gác cổng): upsert_article() dùng ON CONFLICT DO NOTHING.
  3. Structured Analytics: mark_processed() lưu AI insight thành data có cấu trúc.
"""

import os
import logging
import atexit
from typing import List, Optional

import psycopg2
from psycopg2 import pool, OperationalError
from psycopg2.extras import RealDictCursor

from models.article import Article, MarketImpact

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cấu trúc kết nối Supabase (Connection String) dạng:
# postgres-protocol://user.[ref]:[password]@host.com:6543/postgres
DATABASE_URL = os.environ.get("DATABASE_URL")

MAX_RETRY = 3       # Số lần tối đa retry AI cho 1 bài báo
_POOL_MIN = 1       # Số kết nối tối thiểu trong pool
_POOL_MAX = 5       # Số kết nối tối đa — đủ cho pipeline đơn luồng, không bị Supabase chặn

# ===========================================================================
# Connection Pool (Singleton)
# ===========================================================================

_pool: Optional[pool.SimpleConnectionPool] = None


def _get_pool() -> pool.SimpleConnectionPool:
    """
    Trả về Connection Pool. Tạo lần đầu nếu chưa có (lazy init).
    Dùng Pool thay vì mở/đóng kết nối TCP mỗi lần gọi hàm:
      - Tránh 100 handshake cho 100 bài báo.
      - Tuân thủ connection limits của Supabase free tier.
    """
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("Chưa cấu hình DATABASE_URL. Kiểm tra .env hoặc GitHub Secrets.")
        try:
            _pool = pool.SimpleConnectionPool(
                minconn=_POOL_MIN,
                maxconn=_POOL_MAX,
                dsn=DATABASE_URL,
                connect_timeout=10
            )
            # Đảm bảo pool được đóng sạch khi process kết thúc
            atexit.register(_close_pool)
            logger.info(f"✅ Connection pool khởi tạo thành công (min={_POOL_MIN}, max={_POOL_MAX})")
        except OperationalError as e:
            raise RuntimeError(f"Không thể kết nối Supabase: {e}") from e
    return _pool


def _close_pool():
    """Đóng toàn bộ kết nối trong pool khi tắt ứng dụng."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Pool đã đóng.")


# ===========================================================================
# Public API
# ===========================================================================

def init_db():
    """
    Tạo bảng và index nếu chưa có.
    Dùng PostgreSQL native types:
      - TIMESTAMPTZ thay vì TEXT cho timestamps (index-aware, timezone-safe)
      - BOOLEAN thay vì INTEGER cho processed flag
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TIMESTAMPTZ NOT NULL,
                    summary TEXT,
                    sentiment REAL,
                    market_impact TEXT,
                    key_takeaway TEXT,
                    scraped_at TIMESTAMPTZ NOT NULL,
                    processed BOOLEAN DEFAULT FALSE,
                    retry_count INTEGER DEFAULT 0
                )
            ''')
            # Index để truy vấn nhanh bài nào chưa xử lý → tối ưu CPU/RAM
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_processed ON articles(processed)
            ''')
        conn.commit()
        logger.info("✅ DB schema sẵn sàng.")
    except OperationalError as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi init_db: {e}")
        raise
    finally:
        _get_pool().putconn(conn)


def upsert_article(article: Article) -> Optional[bool]:
    """
    Deduplication Gateway:
    Cố gắng chèn bài báo vào DB. Nếu ID (SHA-256 URL) đã tồn tại → Bỏ qua.
    Trả về True nếu tin mới, False nếu tin trùng, None nếu lỗi kết nối DB.
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO articles (
                    id, title, url, source, published_at, summary, scraped_at, processed, retry_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, 0)
                ON CONFLICT (id) DO NOTHING
            ''', (
                article.id,
                article.title,
                str(article.url),
                article.source,
                article.published_at,
                article.summary,
                article.scraped_at
            ))
            is_new = cursor.rowcount > 0
        conn.commit()
        return is_new
    except OperationalError as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi upsert_article (ID: {article.id}): {e}")
        return None
    finally:
        _get_pool().putconn(conn)


def get_unprocessed() -> List[Article]:
    """
    FinOps Engine:
    Lấy danh sách các bài báo thô CHƯA qua AI phân tích (processed = FALSE)
    VÀ chưa vượt quá số lần retry tối đa.
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM articles WHERE processed = FALSE AND retry_count < %s",
                (MAX_RETRY,)
            )
            rows = cursor.fetchall()
    except OperationalError as e:
        logger.error(f"Lỗi kết nối khi get_unprocessed: {e}")
        return []
    finally:
        _get_pool().putconn(conn)

    articles = []
    for row in rows:
        try:
            art = Article(
                url=row['url'],
                title=row['title'],
                source=row['source'],
                published_at=row['published_at'],
                summary=row['summary'],
                scraped_at=row['scraped_at'],
                processed=False
            )
            articles.append(art)
        except Exception as e:
            logger.error(f"Lỗi parse Article từ DB (ID: {row['id']}): {e}", exc_info=True)
            continue

    return articles


def mark_processed(article_id: str, sentiment: Optional[float], market_impact: MarketImpact, key_takeaway: Optional[str]):
    """
    Structured Analytics:
    Cập nhật kết quả AI trả về vào DB và chốt đánh dấu processed = TRUE.
    """
    impact_str = market_impact.value if market_impact else "neutral"
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                UPDATE articles
                SET sentiment = %s,
                    market_impact = %s,
                    key_takeaway = %s,
                    processed = TRUE
                WHERE id = %s
            ''', (sentiment, impact_str, key_takeaway, article_id))
        conn.commit()
    except OperationalError as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi mark_processed (ID: {article_id}): {e}")
    finally:
        _get_pool().putconn(conn)


def increment_retry(article_id: str):
    """
    Tăng retry_count lên 1 khi AI xử lý thất bại.
    Khi retry_count >= MAX_RETRY, get_unprocessed() sẽ tự động bỏ qua bài này.
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE articles SET retry_count = retry_count + 1 WHERE id = %s",
                (article_id,)
            )
        conn.commit()
    except OperationalError as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi increment_retry (ID: {article_id}): {e}")
    finally:
        _get_pool().putconn(conn)
