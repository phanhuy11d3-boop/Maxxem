"""Read-only outbox diagnosis cho bảng signals.

In phân bố tg_status, alert gần nhất, attempts, lỗi cuối, và độ trễ gửi.
Không UPDATE/INSERT — an toàn chạy bất kỳ lúc nào trên production DB.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._env import load_dotenv_if_present  # noqa: E402

load_dotenv_if_present(ROOT)

from psycopg2.extras import RealDictCursor

from storage.postgres import _get_pool  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 72)
            print("SIGNALS OUTBOX DIAGNOSIS (read-only)")
            print("=" * 72)

            cur.execute(
                "SELECT tg_status, COUNT(*) AS n FROM signals GROUP BY tg_status ORDER BY n DESC"
            )
            print("\n-- Phân bố tg_status (toàn bộ lịch sử) --")
            for row in cur.fetchall():
                print(f"  {row['tg_status'] or 'NULL':<10} : {row['n']}")

            cur.execute(
                """
                SELECT base_symbol, quote_symbol, horizon, change_pct, tg_status,
                       tg_attempts, tg_last_error,
                       observed_at,
                       EXTRACT(EPOCH FROM (tg_sent_at - observed_at)) AS send_lag_s
                FROM signals
                ORDER BY observed_at DESC
                LIMIT 15
                """
            )
            print("\n-- 15 signal gần nhất --")
            for row in cur.fetchall():
                lag = f"{row['send_lag_s']:.0f}s" if row["send_lag_s"] is not None else "-"
                err = f" err={row['tg_last_error']}" if row["tg_last_error"] else ""
                print(
                    f"  {row['observed_at']:%m-%d %H:%M} "
                    f"{row['base_symbol']}/{row['quote_symbol']} "
                    f"{row['change_pct']:+.1f}% {row['horizon']} "
                    f"[{row['tg_status']}] attempts={row['tg_attempts']} lag={lag}{err}"
                )

            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE tg_status = 'sent'
                                     AND tg_sent_at > NOW() - INTERVAL '24 hours') AS sent_24h,
                  COUNT(*) FILTER (WHERE tg_status = 'expired'
                                     AND tg_last_attempt_at > NOW() - INTERVAL '24 hours') AS expired_24h,
                  COUNT(*) FILTER (WHERE tg_status IN ('pending','failed')) AS in_queue,
                  COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (tg_sent_at - observed_at)))
                    FILTER (WHERE tg_status='sent'
                              AND tg_sent_at > NOW() - INTERVAL '24 hours'), 0) AS p50_lag_s,
                  COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (tg_sent_at - observed_at)))
                    FILTER (WHERE tg_status='sent'
                              AND tg_sent_at > NOW() - INTERVAL '24 hours'), 0) AS p95_lag_s
                FROM signals
                """
            )
            row = cur.fetchone()
            print("\n-- KPI 24h --")
            print(f"  sent      : {row['sent_24h']}")
            print(f"  expired   : {row['expired_24h']}   (expired > 0 = cadence/delivery có vấn đề)")
            print(f"  in queue  : {row['in_queue']}")
            print(f"  send lag  : p50={row['p50_lag_s']:.0f}s p95={row['p95_lag_s']:.0f}s (SLA 120s)")
    finally:
        _get_pool().putconn(conn)


if __name__ == "__main__":
    main()
