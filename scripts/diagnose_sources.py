"""Read-only source health diagnosis."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._env import load_dotenv_if_present  # noqa: E402

load_dotenv_if_present(ROOT)

from psycopg2 import errors  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from storage.postgres import _get_pool  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 72)
            print("SOURCE HEALTH DIAGNOSIS (read-only)")
            print("=" * 72)
            try:
                cur.execute(
                    """
                    SELECT source, chain_id, stream_id, status, last_seen_at,
                           last_error, consecutive_errors, messages_seen, updated_at,
                           EXTRACT(EPOCH FROM (NOW() - COALESCE(last_seen_at, updated_at))) / 60.0
                             AS age_min
                    FROM source_health
                    ORDER BY source, chain_id, stream_id
                    """
                )
            except errors.UndefinedTable:
                conn.rollback()
                print("source_health table does not exist yet. Run the pipeline once after migration.")
                return

            rows = cur.fetchall()
            if not rows:
                print("No source health rows yet. This is expected before the first post-refactor scan.")
                return

            counts: dict[str, int] = {}
            for row in rows:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            print("\n-- Status counts --")
            for status in ("healthy", "degraded", "unhealthy"):
                print(f"  {status:<9}: {counts.get(status, 0)}")

            print("\n-- Sources --")
            for row in rows:
                last_seen = row["last_seen_at"].strftime("%m-%d %H:%M") if row["last_seen_at"] else "-"
                err = f" err={row['last_error']}" if row["last_error"] else ""
                print(
                    f"  {row['source']:<18} {row['chain_id']:<10} {row['stream_id']:<12} "
                    f"{row['status']:<9} last_seen={last_seen} age={float(row['age_min'] or 0):.1f}m "
                    f"errors={row['consecutive_errors']} messages={row['messages_seen']}{err}"
                )

            print("\nInterpretation:")
            print("  healthy + no triggers = healthy quiet.")
            print("  degraded/unhealthy means quiet is not trustworthy until the source recovers.")
    finally:
        _get_pool().putconn(conn)


if __name__ == "__main__":
    main()
