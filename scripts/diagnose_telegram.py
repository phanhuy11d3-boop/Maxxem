"""
scripts/diagnose_telegram.py
============================
Diagnostic riêng cho vụ "DB lưu cả đống bài nhưng bot không gửi".
Mục tiêu: trả lời các câu hỏi cụ thể bằng SQL đếm trực tiếp trên DB Supabase.

Câu hỏi cần trả lời:
  1. Tổng bài trong DB?
  2. Bao nhiêu processed = TRUE?
  3. Phân bố market_impact (bullish / bearish / neutral / NULL)?
  4. Bao nhiêu bài đáng-gửi (impact in (bullish, bearish))?
  5. Bao nhiêu bài đáng-gửi đã thực sự gửi Telegram (tg_sent = TRUE)?
  6. Bao nhiêu fail TG cần retry (tg_sent = FALSE)?
  7. Phân bố theo nguồn của các bài "đáng gửi nhưng chưa gửi".
  8. 10 key_takeaway gần nhất để xem LLM đang trả về gì.
"""

from __future__ import annotations

import os
import sys
import pathlib
from typing import Iterable

# Cho phép chạy từ root project
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Đọc .env thủ công để khỏi cần python-dotenv
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2
from psycopg2.extras import RealDictCursor


def _print_section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _run(cur, sql: str, params: Iterable | None = None) -> list[dict]:
    cur.execute(sql, params or ())
    return cur.fetchall()


def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Thieu DATABASE_URL"); sys.exit(1)

    conn = psycopg2.connect(db_url, connect_timeout=15)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _print_section("1. TONG QUAN")
            for row in _run(cur, "SELECT COUNT(*) AS total FROM articles"):
                print(f"  Tong bai trong DB                : {row['total']}")
            for row in _run(cur, "SELECT COUNT(*) AS n FROM articles WHERE processed = TRUE"):
                print(f"  Da processed = TRUE              : {row['n']}")
            for row in _run(cur, "SELECT COUNT(*) AS n FROM articles WHERE processed = FALSE"):
                print(f"  Chua processed (queue)           : {row['n']}")
            for row in _run(cur, "SELECT COUNT(*) AS n FROM articles WHERE retry_count >= 3"):
                print(f"  Bi treo retry >= 3               : {row['n']}")

            _print_section("2. PHAN BO MARKET_IMPACT (chi processed=TRUE)")
            rows = _run(
                cur,
                """
                SELECT COALESCE(market_impact, '<NULL>') AS impact, COUNT(*) AS n
                FROM articles
                WHERE processed = TRUE
                GROUP BY impact
                ORDER BY n DESC
                """,
            )
            for r in rows:
                print(f"  {r['impact']:<12} : {r['n']}")

            _print_section("3. ACTIONABLE vs DA GUI TELEGRAM")
            rows = _run(
                cur,
                """
                SELECT
                  COUNT(*) FILTER (WHERE market_impact IN ('bullish','bearish'))                          AS actionable_total,
                  COUNT(*) FILTER (WHERE market_impact IN ('bullish','bearish') AND tg_sent IS TRUE)      AS tg_sent_ok,
                  COUNT(*) FILTER (WHERE market_impact IN ('bullish','bearish') AND tg_sent IS FALSE)    AS tg_sent_fail,
                  COUNT(*) FILTER (WHERE market_impact IN ('bullish','bearish') AND tg_sent IS NULL)     AS tg_sent_null
                FROM articles
                WHERE processed = TRUE
                """,
            )
            for r in rows:
                print(f"  Actionable (bullish+bearish)     : {r['actionable_total']}")
                print(f"   - Da gui Telegram OK            : {r['tg_sent_ok']}")
                print(f"   - Gui FAIL (can retry)          : {r['tg_sent_fail']}")
                print(f"   - tg_sent IS NULL (chua dung)   : {r['tg_sent_null']}  <-- chua bao gio goi send_telegram!")

            _print_section("4. PHAN BO 'ACTIONABLE NHUNG CHUA GUI' THEO NGUON")
            rows = _run(
                cur,
                """
                SELECT source, COUNT(*) AS n
                FROM articles
                WHERE processed = TRUE
                  AND market_impact IN ('bullish','bearish')
                  AND (tg_sent IS NULL OR tg_sent IS FALSE)
                GROUP BY source
                ORDER BY n DESC
                """,
            )
            if not rows:
                print("  (khong co bai nao actionable chua duoc gui)")
            for r in rows:
                print(f"  {r['source']:<22} : {r['n']}")

            _print_section("5. LLM DANG TRA VE GI? (10 bai processed gan nhat)")
            rows = _run(
                cur,
                """
                SELECT scraped_at, source, market_impact, sentiment,
                       LEFT(title, 70)        AS title,
                       LEFT(key_takeaway, 90) AS key_takeaway,
                       tg_sent
                FROM articles
                WHERE processed = TRUE
                ORDER BY scraped_at DESC
                LIMIT 10
                """,
            )
            for r in rows:
                ts = r["scraped_at"].strftime("%m-%d %H:%M") if r["scraped_at"] else "-"
                print(
                    f"  [{ts}] {r['source']:<14} impact={str(r['market_impact']):<8} "
                    f"sent={r['sentiment']!s:<5} tg={r['tg_sent']!s:<5} | {r['title']}"
                )

            _print_section("6. KIEM TRA TRIAGE: bai bi 'Routine news - skipped deep analysis'")
            rows = _run(
                cur,
                """
                SELECT COUNT(*) AS n
                FROM articles
                WHERE processed = TRUE
                  AND key_takeaway = 'Routine news - skipped deep analysis.'
                """,
            )
            print(f"  Bai bi triage 8B loai bo (NEUTRAL)     : {rows[0]['n']}")

            rows = _run(
                cur,
                """
                SELECT COUNT(*) AS n
                FROM articles
                WHERE processed = TRUE
                  AND key_takeaway IS DISTINCT FROM 'Routine news - skipped deep analysis.'
                  AND market_impact = 'neutral'
                """,
            )
            print(f"  Bai bi 70B model phan tich -> NEUTRAL  : {rows[0]['n']}")

            rows = _run(
                cur,
                """
                SELECT COUNT(*) AS n
                FROM articles
                WHERE processed = TRUE
                  AND market_impact IN ('bullish','bearish')
                """,
            )
            print(f"  Bai bi 70B model phan tich -> ACTIONABLE: {rows[0]['n']}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
