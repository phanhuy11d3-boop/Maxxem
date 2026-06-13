"""Read-only check that DB fields are visible in Telegram render.

This catches silent drift such as: fdv exists in signals but no FDV in the
message, score exists but no score line, or dirty legacy symbols leak into tags.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._env import load_dotenv_if_present  # noqa: E402

load_dotenv_if_present(ROOT)

from psycopg2.extras import RealDictCursor  # noqa: E402

from models.pair_signal import clean_symbol  # noqa: E402
from storage.postgres import _get_pool, _row_to_signal  # noqa: E402


def _has(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def _check_row(row: dict) -> list[str]:
    signal = _row_to_signal(row)
    rendered = signal.format_telegram_html()
    issues: list[str] = []

    if row.get("market_cap") is not None and not _has(rendered, "MC "):
        issues.append("market_cap present but MC missing")
    if row.get("fdv") is not None and not _has(rendered, "FDV "):
        issues.append("fdv present but FDV missing")
    if row.get("confidence_score") is not None and "/100" not in rendered:
        issues.append("confidence_score present but score line missing")
    if signal.swap_url and not _has(rendered, "Swap"):
        issues.append("swap_url available but Swap action missing")

    base = clean_symbol(row.get("base_symbol") or "").upper()
    quote = clean_symbol(row.get("quote_symbol") or "").upper()
    if f"{base}/{quote}" not in rendered:
        issues.append("clean pair label missing")
    if f"#{base} #{signal.chain_id.capitalize()}" not in rendered:
        issues.append("clean hashtag line missing")
    if " /" in rendered or "  #" in rendered:
        issues.append("dirty spacing leaked into render")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM signals
                ORDER BY observed_at DESC
                LIMIT %s
                """,
                (args.limit,),
            )
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        _get_pool().putconn(conn)

    failures = 0
    print("=" * 72)
    print("TELEGRAM RENDER ALIGNMENT (read-only)")
    print("=" * 72)
    for row in rows:
        issues = _check_row(row)
        label = _row_to_signal(row).pair_label
        status = "FAIL" if issues else "OK"
        print(f"{status:<4} {row.get('observed_at')} {label} {row.get('horizon')}")
        for issue in issues:
            failures += 1
            print(f"     - {issue}")

    if failures:
        print(f"\nResult: FAIL ({failures} render/backend mismatch issue(s))")
        return 1
    print("\nResult: PASS (render matches checked backend fields)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
