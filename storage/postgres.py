"""
storage/postgres.py
===================
Storage Engine của CryptoSentinel (v3 — DEX-only, Supabase PostgreSQL).

Bảng duy nhất pipeline dùng: ``signals`` — mỗi row là một PairSignal với số
liệu CÓ CẤU TRÚC (không còn nhét số vào text summary rồi parse regex).

Outbox state machine (giữ nguyên thiết kế đã chống gửi-trùng-2-ca thành công):
  tg_status: pending -> sent | failed -> (retry) -> expired
  claim_tg_send_slot: row-lock + lease chống 2 ca production cùng gửi 1 alert.

Bảng ``articles`` cũ của pipeline news KHÔNG bị đụng tới — giữ nguyên trong DB
làm dữ liệu lịch sử, code không đọc/ghi nữa.
"""

import os
import logging
import atexit
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, execute_values

from models.signal import HORIZONS, PairSignal

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

_POOL_MIN = 1
_POOL_MAX = 5

# ===========================================================================
# Connection Pool (Singleton)
# ===========================================================================

_pool: Optional[pool.SimpleConnectionPool] = None


def _get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("Chưa cấu hình DATABASE_URL. Kiểm tra .env hoặc GitHub Secrets.")
        try:
            _pool = pool.SimpleConnectionPool(
                minconn=_POOL_MIN,
                maxconn=_POOL_MAX,
                dsn=DATABASE_URL,
                connect_timeout=10,
            )
            atexit.register(_close_pool)
            logger.info(f"✅ Connection pool khởi tạo thành công (min={_POOL_MIN}, max={_POOL_MAX})")
        except psycopg2.Error as e:
            raise RuntimeError(f"Không thể kết nối Supabase: {e}") from e
    return _pool


def _close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Pool đã đóng.")


# ===========================================================================
# Schema
# ===========================================================================

def init_db():
    """Tạo bảng signals + index nếu chưa có. Idempotent — chạy lại an toàn."""
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    dedup_key TEXT NOT NULL,
                    chain_id TEXT NOT NULL,
                    dex_id TEXT,
                    pair_address TEXT NOT NULL,
                    base_symbol TEXT NOT NULL,
                    quote_symbol TEXT NOT NULL,
                    url TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    change_pct DOUBLE PRECISION NOT NULL,
                    price_usd DOUBLE PRECISION NOT NULL,
                    volume_usd DOUBLE PRECISION NOT NULL,
                    liquidity_usd DOUBLE PRECISION NOT NULL,
                    buys INTEGER NOT NULL DEFAULT 0,
                    sells INTEGER NOT NULL DEFAULT 0,
                    change_m5 DOUBLE PRECISION,
                    change_h1 DOUBLE PRECISION,
                    change_h6 DOUBLE PRECISION,
                    change_h24 DOUBLE PRECISION,
                    fdv DOUBLE PRECISION,
                    market_cap DOUBLE PRECISION,
                    low_liquidity BOOLEAN DEFAULT FALSE,
                    observed_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    tg_status TEXT NOT NULL DEFAULT 'pending',
                    tg_attempts INTEGER NOT NULL DEFAULT 0,
                    tg_last_error TEXT,
                    tg_last_attempt_at TIMESTAMPTZ,
                    tg_sent_at TIMESTAMPTZ
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_outbox ON signals(tg_status, observed_at)"
            )
        conn.commit()
        logger.info("✅ DB schema signals sẵn sàng.")
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi khi init_db: {e}")
        raise
    finally:
        _get_pool().putconn(conn)


# ===========================================================================
# Insert (dedup gateway)
# ===========================================================================

_INSERT_COLS = (
    "id, dedup_key, chain_id, dex_id, pair_address, base_symbol, quote_symbol, "
    "url, horizon, change_pct, price_usd, volume_usd, liquidity_usd, buys, sells, "
    "change_m5, change_h1, change_h6, change_h24, fdv, market_cap, low_liquidity, "
    "observed_at, tg_status, tg_attempts"
)


def _insert_row(sig: PairSignal) -> tuple:
    return (
        sig.id, sig.dedup_key, sig.chain_id, sig.dex_id, sig.pair_address,
        sig.base_symbol, sig.quote_symbol, sig.url, sig.horizon, sig.change_pct,
        sig.price_usd, sig.volume_usd, sig.liquidity_usd, sig.buys, sig.sells,
        sig.changes.get("m5"), sig.changes.get("h1"),
        sig.changes.get("h6"), sig.changes.get("h24"),
        sig.fdv, sig.market_cap, sig.low_liquidity,
        sig.observed_at, "pending", 0,
    )


def insert_signals_batch(signals: List[PairSignal]) -> Tuple[int, int]:
    """
    Dedup Gateway: chèn cả lô, ON CONFLICT (id) DO NOTHING.
    id = sha256(dedup_key) nên cùng pair+horizon+direction+bucket chỉ vào 1 lần
    → cooldown chống spam nằm ngay tại cổng DB.

    Trả về (new_count, db_errors).
    """
    if not signals:
        return 0, 0

    # Cùng id xuất hiện 2 lần trong 1 câu INSERT là lỗi — dedupe nội bộ lô trước.
    seen: dict = {}
    for s in signals:
        if s.id not in seen:
            seen[s.id] = s
    unique = list(seen.values())
    rows = [_insert_row(s) for s in unique]

    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            returned = execute_values(
                cursor,
                f"INSERT INTO signals ({_INSERT_COLS}) VALUES %s "
                "ON CONFLICT (id) DO NOTHING RETURNING id",
                rows,
                page_size=100,
                fetch=True,
            )
        conn.commit()
        return len(returned), 0
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi batch insert signals ({len(unique)} signal): {e}")
        return 0, 1
    finally:
        _get_pool().putconn(conn)


# ===========================================================================
# Outbox state machine
# ===========================================================================

def _row_to_signal(row: dict) -> PairSignal:
    changes = {}
    for h in HORIZONS:
        v = row.get(f"change_{h}")
        if v is not None:
            changes[h] = float(v)
    return PairSignal(
        chain_id=row["chain_id"],
        dex_id=row.get("dex_id") or "",
        pair_address=row["pair_address"],
        base_symbol=row["base_symbol"],
        quote_symbol=row["quote_symbol"],
        url=row["url"],
        horizon=row["horizon"],
        change_pct=float(row["change_pct"]),
        price_usd=float(row["price_usd"]),
        volume_usd=float(row["volume_usd"]),
        liquidity_usd=float(row["liquidity_usd"]),
        buys=int(row.get("buys") or 0),
        sells=int(row.get("sells") or 0),
        changes=changes,
        fdv=row.get("fdv"),
        market_cap=row.get("market_cap"),
        observed_at=row["observed_at"],
        dedup_key=row["dedup_key"],
        low_liquidity=bool(row.get("low_liquidity", False)),
    )


def get_tg_dispatch_queue(max_age_minutes: int = 30, max_attempts: int = 3) -> List[PairSignal]:
    """Queue gửi Telegram: pending/failed, còn tươi, chưa quá max_attempts."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT * FROM signals
                   WHERE tg_status IN ('pending', 'failed')
                     AND tg_attempts < %s
                     AND observed_at > %s
                   ORDER BY observed_at DESC""",
                (max_attempts, cutoff),
            )
            rows = cursor.fetchall()
    except psycopg2.Error as e:
        logger.error(f"Lỗi khi get_tg_dispatch_queue: {e}")
        return []
    finally:
        _get_pool().putconn(conn)

    out: List[PairSignal] = []
    for row in rows:
        try:
            out.append(_row_to_signal(row))
        except Exception as e:
            logger.error(f"Lỗi parse PairSignal từ DB (ID: {row.get('id')}): {e}")
    return out


def claim_tg_send_slot(signal_id: str, lease_seconds: int = 180) -> bool:
    """
    Optimistic claim chống double-dispatch: 2 ca production (local Task Scheduler
    + GH Actions loop) cùng quét outbox. Claim = bump tg_attempts + đóng dấu
    tg_last_attempt_at trong MỘT câu UPDATE; row lock của Postgres serialize —
    kẻ thắng được gửi, kẻ thua nhận 0 row và bỏ qua. Lease chặn re-claim khi kẻ
    thắng còn đang gửi; crash sau claim không kẹt vĩnh viễn (hết lease lại claim
    được, quá cửa sổ stale thì expire_stale_tg_queue dọn).
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE signals
                SET tg_attempts = tg_attempts + 1,
                    tg_last_attempt_at = NOW()
                WHERE id = %s
                  AND tg_status IN ('pending', 'failed')
                  AND (tg_last_attempt_at IS NULL
                       OR tg_last_attempt_at < NOW() - %s * INTERVAL '1 second')
                """,
                (signal_id, lease_seconds),
            )
            claimed = cursor.rowcount > 0
        conn.commit()
        return claimed
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi khi claim_tg_send_slot (ID: {signal_id}): {e}")
        return False
    finally:
        _get_pool().putconn(conn)


def mark_tg_attempt(signal_id: str, success: bool, error: Optional[str] = None) -> None:
    """
    Ghi kết quả một lần gửi:
      success=True  -> tg_status='sent',   tg_sent_at=NOW()
      success=False -> tg_status='failed', tg_last_error=error
    tg_attempts do claim_tg_send_slot() tăng — KHÔNG tăng lại ở đây.
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE signals
                SET tg_last_attempt_at = NOW(),
                    tg_last_error = %s,
                    tg_status = %s,
                    tg_sent_at = CASE WHEN %s THEN NOW() ELSE tg_sent_at END
                WHERE id = %s
                """,
                (
                    None if success else (error or "send_failed"),
                    "sent" if success else "failed",
                    success,
                    signal_id,
                ),
            )
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Lỗi khi mark_tg_attempt (ID: {signal_id}): {e}")
    finally:
        _get_pool().putconn(conn)


def expire_stale_tg_queue(max_age_minutes: int = 30) -> int:
    """
    Alert giá quá cửa sổ tươi = vô giá trị với trader, có thể gây hại.
    Đánh dấu expired thay vì gửi muộn. Trả về số row expired.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE signals
                SET tg_status = 'expired',
                    tg_last_error = 'stale_expired',
                    tg_last_attempt_at = NOW()
                WHERE tg_status IN ('pending', 'failed')
                  AND observed_at <= %s
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


def get_outbox_kpis(max_age_minutes: int = 30) -> dict:
    """KPI heartbeat: pending/failed còn tươi, expired 60', tuổi pending già nhất."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                  COUNT(*) FILTER (
                    WHERE tg_status = 'pending' AND observed_at > %s
                  ) AS pending_count,
                  COUNT(*) FILTER (
                    WHERE tg_status = 'failed' AND observed_at > %s
                  ) AS failed_count,
                  COUNT(*) FILTER (
                    WHERE tg_status = 'expired'
                      AND tg_last_attempt_at > NOW() - INTERVAL '60 minutes'
                  ) AS expired_count_60m,
                  COALESCE(
                    MAX(EXTRACT(EPOCH FROM (NOW() - observed_at)) / 60.0)
                      FILTER (WHERE tg_status IN ('pending', 'failed') AND observed_at > %s),
                    0
                  ) AS oldest_pending_age_min
                FROM signals
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
