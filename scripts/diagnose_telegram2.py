"""
diagnose_telegram2.py
Phan tich theo thoi gian va theo nguon de tach 'bai cu' khoi 'bai moi sau khi co code mark_tg_sent'.
"""
from __future__ import annotations
import os, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Phan bo theo NGAY scraped_at cua cac actionable chua gui
        print("=" * 72)
        print("ACTIONABLE chua gui (tg_sent IS NULL) — phan bo theo ngay scraped_at")
        print("=" * 72)
        cur.execute(
            """
            SELECT DATE(scraped_at) AS d, COUNT(*) AS n
            FROM articles
            WHERE processed = TRUE
              AND market_impact IN ('bullish','bearish')
              AND tg_sent IS NULL
            GROUP BY d ORDER BY d DESC
            """
        )
        for r in cur.fetchall():
            print(f"  {r['d']}  : {r['n']}")

        # Bai actionable scraped TRONG VONG 6h
        print()
        print("=" * 72)
        print("ACTIONABLE chua gui scraped TRONG 6h gan nhat (theo source)")
        print("=" * 72)
        cur.execute(
            """
            SELECT source, COUNT(*) AS n
            FROM articles
            WHERE processed = TRUE
              AND market_impact IN ('bullish','bearish')
              AND tg_sent IS NULL
              AND scraped_at > NOW() - INTERVAL '6 hours'
            GROUP BY source ORDER BY n DESC
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("  (khong co bai actionable nao trong 6h gan nhat)")
        for r in rows:
            print(f"  {r['source']:<22} : {r['n']}")

        # Phan bo retry_count cua bai chua processed (queue stuck)
        print()
        print("=" * 72)
        print("QUEUE chua processed — phan bo theo retry_count va source")
        print("=" * 72)
        cur.execute(
            """
            SELECT source, retry_count, COUNT(*) AS n
            FROM articles
            WHERE processed = FALSE
            GROUP BY source, retry_count ORDER BY retry_count DESC, n DESC
            """
        )
        for r in cur.fetchall():
            print(f"  retry={r['retry_count']}  {r['source']:<22} : {r['n']}")

        # 5 bai actionable moi nhat — co dung scraped_at gan day khong?
        print()
        print("=" * 72)
        print("10 bai actionable moi nhat (theo scraped_at)")
        print("=" * 72)
        cur.execute(
            """
            SELECT scraped_at, source, market_impact, tg_sent, LEFT(title, 80) AS title
            FROM articles
            WHERE processed = TRUE AND market_impact IN ('bullish','bearish')
            ORDER BY scraped_at DESC LIMIT 10
            """
        )
        for r in cur.fetchall():
            print(
                f"  {r['scraped_at'].strftime('%m-%d %H:%M')} {r['source']:<14} "
                f"impact={r['market_impact']:<8} tg_sent={r['tg_sent']!s:<5} | {r['title']}"
            )

        # Co bai nao tg_sent IS NOT NULL khong?
        print()
        print("=" * 72)
        print("Bai DA tung duoc goi mark_tg_sent (tg_sent IS NOT NULL)")
        print("=" * 72)
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE tg_sent IS TRUE)  AS ok,
                   COUNT(*) FILTER (WHERE tg_sent IS FALSE) AS fail
            FROM articles
            """
        )
        r = cur.fetchone()
        print(f"  tg_sent = TRUE  (gui OK)         : {r['ok']}")
        print(f"  tg_sent = FALSE (gui FAIL)       : {r['fail']}")

    conn.close()


if __name__ == "__main__":
    main()
