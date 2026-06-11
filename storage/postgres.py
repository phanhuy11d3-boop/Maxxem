"""
storage/postgres.py
===================
Storage Engine của CryptoSentinel (v2.2 — Supabase PostgreSQL, Production-grade).

Thay đổi từ v2.1 (sqlite.py):
  - ĐỔI TÊN: sqlite.py → postgres.py (đúng Single Responsibility, không gây nhầm lẫn).
  - FIX DATA TYPES: TEXT timestamps → TIMESTAMPTZ, INTEGER boolean → BOOLEAN.
  - FIX CONNECTION PATTERN: Mở/đóng per-call → SimpleConnectionPool (tái sử dụng kết nối).
  - FIX ERROR HANDLING: try/except psycopg2.Error (mọi lỗi DB, không chỉ OperationalError)
    cho toàn bộ DB ops — rollback trước khi trả connection về pool, pipeline không crash
    vì một câu UPDATE lỗi dữ liệu.

Triết lý thiết kế (giữ nguyên):
  1. FinOps (Token Management): get_unprocessed() chặn gọi AI cho tin cũ.
  2. Deduplication (Gác cổng): upsert_article() dùng ON CONFLICT DO NOTHING.
  3. Structured Analytics: mark_processed() lưu AI insight thành data có cấu trúc.
"""

import os
import logging
import atexit
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, execute_values

from models.article import Article, MarketImpact, normalize_market_impact

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
        except psycopg2.Error as e:
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
                    dedup_key TEXT,
                    source TEXT NOT NULL,
                    published_at TIMESTAMPTZ NOT NULL,
                    published_from_source BOOLEAN DEFAULT TRUE,
                    summary TEXT,
                    sentiment REAL,
                    market_impact TEXT,
                    key_takeaway TEXT,
                    narrative_tag TEXT,
                    affected_tokens TEXT[],
                    urgency TEXT,
                    low_confidence BOOLEAN DEFAULT FALSE,
                    tg_sent BOOLEAN DEFAULT NULL,
                    tg_status TEXT DEFAULT NULL,
                    tg_attempts INTEGER DEFAULT 0,
                    tg_last_error TEXT,
                    tg_last_attempt_at TIMESTAMPTZ,
                    tg_sent_at TIMESTAMPTZ,
                    scraped_at TIMESTAMPTZ NOT NULL,
                    processed BOOLEAN DEFAULT FALSE,
                    retry_count INTEGER DEFAULT 0
                )
            ''')
            # Migrate: thêm cột mới cho DB đã tồn tại trước khi có schema này
            for col_sql in [
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS narrative_tag TEXT",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS affected_tokens TEXT[]",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS dedup_key TEXT",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS urgency TEXT",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS low_confidence BOOLEAN DEFAULT FALSE",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_from_source BOOLEAN DEFAULT TRUE",
                # tg_sent: NULL=chưa cần gửi (neutral), TRUE=đã gửi OK, FALSE=fail cần retry
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS tg_sent BOOLEAN DEFAULT NULL",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS tg_status TEXT DEFAULT NULL",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS tg_attempts INTEGER DEFAULT 0",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS tg_last_error TEXT",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS tg_last_attempt_at TIMESTAMPTZ",
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS tg_sent_at TIMESTAMPTZ",
            ]:
                cursor.execute(col_sql)
            # Index để truy vấn nhanh bài nào chưa xử lý → tối ưu CPU/RAM
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_processed ON articles(processed)
            ''')
        conn.commit()
        logger.info("✅ DB schema sẵn sàng.")
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi init_db: {e}")
        raise
    finally:
        _get_pool().putconn(conn)


def _insert_row_for_article(article: Article) -> tuple:
    impact = article.market_impact.value if article.market_impact else None
    is_actionable = article.processed and article.market_impact in (
        MarketImpact.BULLISH,
        MarketImpact.BEARISH,
    )
    return (
        article.id,
        article.title,
        str(article.url),
        article.dedup_key,
        article.source,
        article.published_at,
        article.published_from_source,
        article.summary,
        article.sentiment,
        impact,
        article.key_takeaway,
        article.narrative_tag,
        article.affected_tokens,
        article.urgency,
        article.low_confidence,
        None,
        "pending" if is_actionable else None,
        0,
        article.scraped_at,
        article.processed,
        0,
    )


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
                    id, title, url, dedup_key, source, published_at, published_from_source,
                    summary, sentiment, market_impact, key_takeaway, narrative_tag,
                    affected_tokens, urgency, low_confidence, tg_sent, tg_status,
                    tg_attempts, scraped_at, processed, retry_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            ''', _insert_row_for_article(article))
            is_new = cursor.rowcount > 0
        conn.commit()
        return is_new
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi upsert_article (ID: {article.id}): {e}")
        return None
    finally:
        _get_pool().putconn(conn)


def upsert_articles_batch(articles: List[Article]) -> Tuple[int, int]:
    """
    Batch Deduplication Gateway: chèn cả lô bằng execute_values (1-2 round-trip)
    thay vì N round-trip lẻ — đo thực tế 2026-06-11: ~400 bài × ~0.5s/bài = ~200s/vòng,
    chiếm 87% thời gian pipeline và ăn gần hết cửa sổ stale 30 phút.

    Trả về (new_count, db_errors). Nếu cả lô fail (psycopg2.Error) → fallback
    per-article qua upsert_article() để một bài hỏng không nuốt cả lô.
    """
    if not articles:
        return 0, 0

    # ON CONFLICT DO NOTHING cấm cùng một id xuất hiện 2 lần trong cùng câu INSERT
    # → dedupe nội bộ lô trước, giữ bản đầu tiên.
    seen: dict = {}
    for a in articles:
        if a.id not in seen:
            seen[a.id] = a
    unique = list(seen.values())

    rows = [_insert_row_for_article(a) for a in unique]

    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            returned = execute_values(
                cursor,
                '''
                INSERT INTO articles (
                    id, title, url, dedup_key, source, published_at, published_from_source,
                    summary, sentiment, market_impact, key_takeaway, narrative_tag,
                    affected_tokens, urgency, low_confidence, tg_sent, tg_status,
                    tg_attempts, scraped_at, processed, retry_count
                ) VALUES %s
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                ''',
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                page_size=200,
                fetch=True,
            )
        conn.commit()
        return len(returned), 0
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi batch upsert ({len(unique)} bài) → fallback per-article: {e}")
    finally:
        _get_pool().putconn(conn)

    new_count = 0
    db_errors = 0
    for a in unique:
        result = upsert_article(a)
        if result is None:
            db_errors += 1
        elif result:
            new_count += 1
    return new_count, db_errors


def get_unprocessed() -> List[Article]:
    """
    FinOps Engine:
    Lấy danh sách các bài báo thô CHƯA qua AI phân tích (processed = FALSE)
    VÀ chưa vượt quá số lần retry tối đa.
    """
    conn = _get_pool().getconn()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT * FROM articles
                   WHERE processed = FALSE
                     AND retry_count < %s
                     AND COALESCE(published_at, scraped_at) > %s
                   ORDER BY scraped_at DESC""",
                (MAX_RETRY, cutoff)
            )
            rows = cursor.fetchall()
    except psycopg2.Error as e:
        logger.error(f"Lỗi kết nối khi get_unprocessed: {e}")
        return []
    finally:
        _get_pool().putconn(conn)

    articles = []
    for row in rows:
        try:
            art = Article(
                url=row['url'],
                dedup_key=row.get('dedup_key'),
                title=row['title'],
                source=row['source'],
                published_at=row['published_at'],
                published_from_source=bool(row.get('published_from_source', True)),
                summary=row['summary'],
                scraped_at=row['scraped_at'],
                narrative_tag=row.get('narrative_tag'),
                affected_tokens=row.get('affected_tokens'),
                urgency=row.get('urgency'),
                low_confidence=bool(row.get('low_confidence', False)),
                processed=False,
            )
            articles.append(art)
        except Exception as e:
            logger.error(f"Lỗi parse Article từ DB (ID: {row['id']}): {e}", exc_info=True)
            continue

    return articles


def mark_processed(
    article_id: str,
    sentiment: Optional[float],
    market_impact: MarketImpact,
    key_takeaway: Optional[str],
    narrative_tag: Optional[str] = None,
    affected_tokens: Optional[List[str]] = None,
    urgency: Optional[str] = None,
):
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
                    narrative_tag = %s,
                    affected_tokens = %s,
                    urgency = %s,
                    processed = TRUE
                WHERE id = %s
            ''', (sentiment, impact_str, key_takeaway, narrative_tag, affected_tokens, urgency, article_id))
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi mark_processed (ID: {article_id}): {e}")
    finally:
        _get_pool().putconn(conn)


def mark_processed_with_tg(
    article_id: str,
    sentiment: Optional[float],
    market_impact: MarketImpact,
    key_takeaway: Optional[str],
    narrative_tag: Optional[str] = None,
    affected_tokens: Optional[List[str]] = None,
    urgency: Optional[str] = None,
    *,
    low_confidence: bool = False,
    tg_sent: Optional[bool] = None,
    tg_status: Optional[str] = None,
    tg_attempts: Optional[int] = None,
) -> None:
    """
    Atomic write: mark_processed + tg_sent trong cùng 1 UPDATE.

    Vector 3d fix: trước đây mark_processed (line A) và mark_tg_sent (line B) là 2
    UPDATE riêng. Nếu pipeline crash giữa A và B, bài sẽ ở trạng thái processed=TRUE
    nhưng tg_sent=NULL, khiến lần chạy sau "vớt" lại bài cũ và phun ra Telegram.
    Hàm này gộp cả hai trong 1 UPDATE để chỉ có 2 outcome:
      - cả processed + tg_sent ghi nhận thành công, hoặc
      - cả hai chưa ghi (DB rollback) → bài còn ở queue cũ, sẽ được phân tích lại.

    ``tg_sent``:
      - None  : bài neutral, không cần gửi.
      - True  : bài actionable đã gửi Telegram thành công.
      - False : bài actionable nhưng gửi Telegram thất bại → retry trong cửa sổ 30 phút.
    """
    impact_str = market_impact.value if market_impact else "neutral"
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE articles
                SET sentiment = %s,
                    market_impact = %s,
                    key_takeaway = %s,
                    narrative_tag = %s,
                    affected_tokens = %s,
                    urgency = %s,
                    low_confidence = %s,
                    tg_sent = %s,
                    tg_status = %s,
                    tg_attempts = COALESCE(%s, tg_attempts),
                    processed = TRUE
                WHERE id = %s
                """,
                (
                    sentiment, impact_str, key_takeaway, narrative_tag,
                    affected_tokens, urgency, low_confidence, tg_sent, tg_status, tg_attempts, article_id,
                ),
            )
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(
            "Lỗi kết nối khi mark_processed_with_tg (ID: %s): %s",
            article_id, e,
        )
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
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi kết nối khi increment_retry (ID: {article_id}): {e}")
    finally:
        _get_pool().putconn(conn)


def mark_tg_sent(article_id: str, success: bool) -> None:
    """Ghi lại kết quả gửi Telegram: TRUE=OK, FALSE=fail cần retry lần sau."""
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE articles SET tg_sent = %s WHERE id = %s",
                (success, article_id)
            )
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi khi mark_tg_sent (ID: {article_id}): {e}")
    finally:
        _get_pool().putconn(conn)


def mark_tg_attempt(article_id: str, success: bool, error: Optional[str] = None) -> None:
    """
    Ghi kết quả một lần gửi Telegram theo state machine:
      - success=True  -> tg_status='sent',   tg_sent=TRUE,  tg_sent_at=NOW()
      - success=False -> tg_status='failed', tg_sent=FALSE, tg_last_error=error
    Đồng thời tăng tg_attempts +1 và ghi tg_last_attempt_at.
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE articles
                SET tg_attempts = COALESCE(tg_attempts, 0) + 1,
                    tg_last_attempt_at = NOW(),
                    tg_last_error = %s,
                    tg_sent = %s,
                    tg_status = %s,
                    tg_sent_at = CASE WHEN %s THEN NOW() ELSE tg_sent_at END
                WHERE id = %s
                """,
                (
                    None if success else (error or "send_failed"),
                    success,
                    "sent" if success else "failed",
                    success,
                    article_id,
                ),
            )
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi khi mark_tg_attempt (ID: {article_id}): {e}")
    finally:
        _get_pool().putconn(conn)


def expire_stale_tg_queue(max_age_minutes: int = 30) -> int:
    """
    Đánh dấu EXPIRED cho các bài actionable còn pending/failed nhưng đã quá stale.
    PM rule: tin quá 30 phút ở đầu queue => discard + log, không retry.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE articles
                SET tg_status = 'expired',
                    tg_last_error = 'stale_expired',
                    tg_sent = FALSE,
                    tg_last_attempt_at = NOW()
                WHERE processed = TRUE
                  AND market_impact IN ('bullish', 'bearish')
                  AND COALESCE(tg_status, CASE WHEN tg_sent IS TRUE THEN 'sent'
                                               WHEN tg_sent IS FALSE THEN 'failed'
                                               ELSE 'pending' END) IN ('pending', 'failed')
                  AND COALESCE(published_at, scraped_at) <= %s
                """,
                (cutoff,),
            )
            expired = cursor.rowcount
        conn.commit()
        return int(expired)
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi khi expire_stale_tg_queue: {e}")
        return 0
    finally:
        _get_pool().putconn(conn)


def get_tg_dispatch_queue(max_age_minutes: int = 30, max_attempts: int = 3) -> List[Article]:
    """
    Lấy queue gửi Telegram theo state machine:
      - trạng thái pending/failed
      - còn trong cửa sổ live (<= max_age_minutes)
      - chưa vượt max_attempts
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=max_age_minutes)
    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT * FROM articles
                   WHERE processed = TRUE
                     AND market_impact IN ('bullish', 'bearish')
                     AND COALESCE(tg_status, CASE WHEN tg_sent IS TRUE THEN 'sent'
                                                  WHEN tg_sent IS FALSE THEN 'failed'
                                                  ELSE 'pending' END) IN ('pending', 'failed')
                     AND COALESCE(tg_attempts, 0) < %s
                     AND COALESCE(published_at, scraped_at) > %s
                   ORDER BY scraped_at DESC""",
                (max_attempts, cutoff),
            )
            rows = cursor.fetchall()
    except psycopg2.Error as e:
        logger.error(f"Lỗi khi get_tg_failed: {e}")
        return []
    finally:
        _get_pool().putconn(conn)

    articles = []
    for row in rows:
        try:
            art = Article(
                url=row['url'],
                dedup_key=row.get('dedup_key'),
                title=row['title'],
                source=row['source'],
                published_at=row['published_at'],
                published_from_source=bool(row.get('published_from_source', True)),
                summary=row['summary'],
                scraped_at=row['scraped_at'],
                sentiment=row.get('sentiment'),
                market_impact=normalize_market_impact(row['market_impact']) if row.get('market_impact') else None,
                key_takeaway=row.get('key_takeaway'),
                narrative_tag=row.get('narrative_tag'),
                affected_tokens=row.get('affected_tokens'),
                urgency=row.get('urgency'),
                low_confidence=bool(row.get('low_confidence', False)),
                processed=True,
            )
            articles.append(art)
        except Exception as e:
            logger.error(f"Lỗi parse Article TG-failed (ID: {row['id']}): {e}")
    return articles


def get_tg_failed(max_age_minutes: int = 30) -> List[Article]:
    """
    Backward-compatible alias (legacy callers).
    """
    return get_tg_dispatch_queue(max_age_minutes=max_age_minutes, max_attempts=3)


def get_outbox_kpis(max_age_minutes: int = 30) -> dict:
    """
    KPI cho heartbeat vận hành outbox.

    Trả về:
      - pending_count
      - failed_count
      - expired_count_60m
      - oldest_pending_age_min  (quan trọng nhất cho cửa sổ can thiệp trước 30m)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                  COUNT(*) FILTER (
                    WHERE processed = TRUE
                      AND market_impact IN ('bullish','bearish')
                      AND tg_status = 'pending'
                      AND COALESCE(published_at, scraped_at) > %s
                  ) AS pending_count,
                  COUNT(*) FILTER (
                    WHERE processed = TRUE
                      AND market_impact IN ('bullish','bearish')
                      AND tg_status = 'failed'
                      AND COALESCE(published_at, scraped_at) > %s
                  ) AS failed_count,
                  COUNT(*) FILTER (
                    WHERE tg_status = 'expired'
                      AND tg_last_attempt_at > NOW() - INTERVAL '60 minutes'
                  ) AS expired_count_60m,
                  COALESCE(
                    MAX(
                      EXTRACT(EPOCH FROM (NOW() - COALESCE(published_at, scraped_at))) / 60.0
                    ) FILTER (
                      WHERE processed = TRUE
                        AND market_impact IN ('bullish','bearish')
                        AND tg_status IN ('pending','failed')
                        AND COALESCE(published_at, scraped_at) > %s
                    ),
                    0
                  ) AS oldest_pending_age_min
                FROM articles
                """,
                (cutoff, cutoff, cutoff),
            )
            row = cursor.fetchone() or {}
            return {
                "pending_count": int(row.get("pending_count") or 0),
                "failed_count": int(row.get("failed_count") or 0),
                "expired_count_60m": int(row.get("expired_count_60m") or 0),
                "oldest_pending_age_min": float(row.get("oldest_pending_age_min") or 0.0),
            }
    except psycopg2.Error as e:
        logger.error("Lỗi khi get_outbox_kpis: %s", e)
        return {
            "pending_count": 0,
            "failed_count": 0,
            "expired_count_60m": 0,
            "oldest_pending_age_min": 0.0,
        }
    finally:
        _get_pool().putconn(conn)
