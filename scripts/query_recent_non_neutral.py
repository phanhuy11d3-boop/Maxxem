"""
Query 10 bai non-neutral gan nhat trong DB, chi lay bai con "live" <= 30 phut.

Usage:
  py -3 scripts/query_recent_non_neutral.py
  py -3 scripts/query_recent_non_neutral.py --limit 10 --max-age-minutes 30
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


def load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    # json.dumps gọi default cho MỌI type không serialize được; trả lại
    # nguyên object (vd Decimal) sẽ ném "Circular reference detected".
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lay 10 bai non-neutral gan nhat, con trong cua so <= 30 phut."
    )
    parser.add_argument("--limit", type=int, default=10, help="So dong toi da (mac dinh 10).")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=30,
        help="Nguong tuoi bai theo phut (mac dinh 30).",
    )
    args = parser.parse_args()

    load_env()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Thieu DATABASE_URL (kiem tra .env).")

    conn = psycopg2.connect(db_url, connect_timeout=15)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  id,
                  source,
                  title,
                  market_impact,
                  sentiment,
                  low_confidence,
                  processed,
                  tg_status,
                  tg_sent,
                  tg_attempts,
                  published_at,
                  scraped_at,
                  EXTRACT(
                    EPOCH FROM (NOW() - COALESCE(published_at, scraped_at))
                  ) / 60.0 AS age_minutes
                FROM articles
                WHERE market_impact IN ('bullish', 'bearish')
                  AND COALESCE(published_at, scraped_at) > NOW() - (%s * INTERVAL '1 minute')
                ORDER BY scraped_at DESC
                LIMIT %s
                """,
                (args.max_age_minutes, args.limit),
            )
            rows = cur.fetchall()

        payload = {
            "limit": args.limit,
            "max_age_minutes": args.max_age_minutes,
            "count": len(rows),
            "rows": rows,
        }
        print(json.dumps(payload, ensure_ascii=False, default=to_jsonable, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
