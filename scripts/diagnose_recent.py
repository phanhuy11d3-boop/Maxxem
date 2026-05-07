"""
Phan tich xu ly TAM DOAN TRONG 36h gan day.
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
        # Count articles processed since b104b51 deployment (~2026-05-06 04:30 UTC = 11:30 ICT)
        # Use scraped_at as proxy for processing time
        print("=" * 72)
        print("Phan bo market_impact theo nguong THOI GIAN 'sau khi deploy code moi'")
        print("=" * 72)

        for label, sql in [
            ("Truoc 2026-05-06 04:00 UTC (code cu)",
             "scraped_at < '2026-05-06 04:00:00+00'"),
            ("Tu 2026-05-06 04:00 UTC tro di (code moi b104b51+)",
             "scraped_at >= '2026-05-06 04:00:00+00'"),
            ("Trong 24h gan nhat",
             "scraped_at > NOW() - INTERVAL '24 hours'"),
        ]:
            print(f"\n--- {label}")
            cur.execute(
                f"""
                SELECT COALESCE(market_impact, '<unproc>') AS impact, COUNT(*) AS n
                FROM articles
                WHERE {sql}
                GROUP BY impact ORDER BY n DESC
                """
            )
            rows = cur.fetchall()
            for r in rows:
                print(f"   {r['impact']:<12} : {r['n']}")

        # Bay luot cua 70B model trong 24h: bao nhieu high_impact qua duoc triage
        print()
        print("=" * 72)
        print("Trong 24h: Triage so luong, da NEUTRAL boi 70B vs ACTIONABLE")
        print("=" * 72)
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE key_takeaway = 'Routine news - skipped deep analysis.')                  AS triage_skip,
              COUNT(*) FILTER (WHERE key_takeaway IS DISTINCT FROM 'Routine news - skipped deep analysis.'
                                 AND market_impact = 'neutral')                                              AS llm_neutral,
              COUNT(*) FILTER (WHERE market_impact IN ('bullish','bearish'))                                AS llm_actionable,
              COUNT(*) FILTER (WHERE processed = FALSE)                                                     AS still_unprocessed
            FROM articles
            WHERE scraped_at > NOW() - INTERVAL '24 hours'
            """
        )
        r = cur.fetchone()
        print(f"  Triage 8B loai (NEUTRAL)            : {r['triage_skip']}")
        print(f"  70B chay -> NEUTRAL                 : {r['llm_neutral']}")
        print(f"  70B chay -> ACTIONABLE (bull/bear)  : {r['llm_actionable']}")
        print(f"  Con chua processed (queue/stuck)    : {r['still_unprocessed']}")

        # Last 10 articles processed by 70B (NOT triage skip), see if LLM is being too conservative
        print()
        print("=" * 72)
        print("10 bai gan day duoc 70B phan tich (key_takeaway != 'Routine...'):")
        print("=" * 72)
        cur.execute(
            """
            SELECT scraped_at, source, market_impact, sentiment,
                   LEFT(title, 70)        AS title,
                   LEFT(key_takeaway, 80) AS key_takeaway
            FROM articles
            WHERE processed = TRUE
              AND key_takeaway IS DISTINCT FROM 'Routine news - skipped deep analysis.'
              AND scraped_at > NOW() - INTERVAL '24 hours'
            ORDER BY scraped_at DESC LIMIT 10
            """
        )
        for r in cur.fetchall():
            ts = r["scraped_at"].strftime("%m-%d %H:%M")
            print(f"  [{ts}] {r['source']:<14} {r['market_impact']:<8} sent={r['sentiment']!s:<5} | {r['title']}")
            print(f"          take: {r['key_takeaway']}")

    conn.close()


if __name__ == "__main__":
    main()
