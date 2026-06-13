"""Read-only alert-rate and backpressure diagnosis."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._env import load_dotenv_if_present  # noqa: E402

load_dotenv_if_present(ROOT)

from psycopg2.extras import RealDictCursor  # noqa: E402

from models.pair_signal import clean_symbol  # noqa: E402
from storage.postgres import _get_pool  # noqa: E402

WINDOW_HOURS = 24


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 72)
            print(f"ALERT RATE DIAGNOSIS (read-only, last {WINDOW_HOURS}h)")
            print("=" * 72)

            cur.execute(
                """
                SELECT base_symbol, quote_symbol, chain_id, horizon,
                       COUNT(*) AS n,
                       MAX(ABS(change_pct)) AS max_abs_change,
                       AVG(confidence_score) AS avg_score
                FROM signals
                WHERE observed_at > NOW() - (%s * INTERVAL '1 hour')
                GROUP BY base_symbol, quote_symbol, chain_id, horizon
                ORDER BY n DESC, max_abs_change DESC
                LIMIT 20
                """,
                (WINDOW_HOURS,),
            )
            print("\n-- Top pair/horizon by alert count --")
            rows = cur.fetchall()
            if not rows:
                print("  No alerts in window.")
            for row in rows:
                avg_score = "-" if row["avg_score"] is None else f"{row['avg_score']:.1f}"
                pair = (
                    f"{clean_symbol(row['base_symbol']).upper()}/"
                    f"{clean_symbol(row['quote_symbol']).upper()}"
                )
                print(
                    f"  {pair} {row['chain_id']} "
                    f"{row['horizon']:<3} n={row['n']:<3} "
                    f"max_abs={row['max_abs_change']:.1f}% avg_score={avg_score}"
                )

            cur.execute(
                """
                SELECT tg_status, COUNT(*) AS n
                FROM signals
                WHERE observed_at > NOW() - (%s * INTERVAL '1 hour')
                GROUP BY tg_status
                ORDER BY n DESC
                """,
                (WINDOW_HOURS,),
            )
            print("\n-- Delivery state in window --")
            for row in cur.fetchall():
                print(f"  {row['tg_status']:<8}: {row['n']}")

            cur.execute(
                """
                SELECT COUNT(*) AS pending_fresh
                FROM signals
                WHERE tg_status IN ('pending', 'failed')
                  AND observed_at > NOW() - INTERVAL '30 minutes'
                """
            )
            pending = int((cur.fetchone() or {}).get("pending_fresh") or 0)
            print("\n-- Backpressure --")
            print(f"  fresh pending/failed: {pending}")
            if pending >= 10:
                print("  status: DEGRADED - queue is large enough to prioritize dispatch.")
            else:
                print("  status: OK")
    finally:
        _get_pool().putconn(conn)


if __name__ == "__main__":
    main()
