"""Read-only threshold backtest from stored alerts.

This first pass uses the ``signals`` table, so it can only analyze moves that
already crossed historical thresholds. If pair snapshot archiving is enabled in
a future phase, this script can be extended to replay non-triggering ticks too.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._env import load_dotenv_if_present  # noqa: E402

load_dotenv_if_present(ROOT)

from psycopg2.extras import RealDictCursor  # noqa: E402

from storage.postgres import _get_pool  # noqa: E402

WINDOW_HOURS = 168


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 72)
            print(f"THRESHOLD BACKTEST (read-only, stored alerts, last {WINDOW_HOURS}h)")
            print("=" * 72)

            cur.execute(
                """
                SELECT base_symbol, quote_symbol, chain_id,
                       COUNT(*) AS alerts,
                       COUNT(*) FILTER (WHERE ABS(change_pct) >= 15) AS hot_abs,
                       AVG(ABS(change_pct)) AS avg_abs_change,
                       MAX(ABS(change_pct)) AS max_abs_change
                FROM signals
                WHERE observed_at > NOW() - (%s * INTERVAL '1 hour')
                GROUP BY base_symbol, quote_symbol, chain_id
                ORDER BY alerts DESC, max_abs_change DESC
                LIMIT 25
                """,
                (WINDOW_HOURS,),
            )
            rows = cur.fetchall()
            print("\n-- Pair pressure --")
            if not rows:
                print("  No stored alerts in window.")
            for row in rows:
                print(
                    f"  {row['base_symbol']}/{row['quote_symbol']} {row['chain_id']:<10} "
                    f"alerts={row['alerts']:<3} hot_abs={row['hot_abs']:<3} "
                    f"avg_abs={row['avg_abs_change']:.1f}% max_abs={row['max_abs_change']:.1f}%"
                )

            cur.execute(
                """
                SELECT horizon, COUNT(*) AS alerts,
                       AVG(ABS(change_pct)) AS avg_abs_change,
                       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY ABS(change_pct)) AS p90_abs_change
                FROM signals
                WHERE observed_at > NOW() - (%s * INTERVAL '1 hour')
                GROUP BY horizon
                ORDER BY alerts DESC
                """,
                (WINDOW_HOURS,),
            )
            print("\n-- Horizon pressure --")
            for row in cur.fetchall():
                print(
                    f"  {row['horizon']:<3} alerts={row['alerts']:<3} "
                    f"avg_abs={row['avg_abs_change']:.1f}% p90_abs={row['p90_abs_change']:.1f}%"
                )

            print("\nInterpretation:")
            print("  High alerts for one pair/horizon usually means tune that pair override first.")
            print("  This does not prove missed moves; it only analyzes already-stored alerts.")
    finally:
        _get_pool().putconn(conn)


if __name__ == "__main__":
    main()
