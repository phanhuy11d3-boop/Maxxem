"""
diagnose_pipeline.py
====================
Mo phong CHINH XAC luong _process_chunk de tim ra noi 'mat' send_telegram.
Ket noi DB that, lay 1 chunk, chay full triage + analyze, in trang thai cua
TUNG bai sau moi buoc — KHONG goi mark_processed/send_telegram (read-only).
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

from models.article import Article, MarketImpact
from processors.insight_extractor import (
    get_groq_client, triage_articles, analyze_articles_batch,
)


def _load_recent_chunk(limit: int = 8) -> list[Article]:
    """Lay vai bai gan day (bat ke processed) de re-analyze va so sanh."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM articles
                   ORDER BY scraped_at DESC LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    articles: list[Article] = []
    for row in rows:
        try:
            art = Article(
                url=row["url"], title=row["title"], source=row["source"],
                published_at=row["published_at"], summary=row["summary"],
                scraped_at=row["scraped_at"], processed=False,
            )
        except Exception as e:
            print(f"  bo qua row {row['id'][:12]}: {e}")
            continue
        articles.append(art)
        # In hash de so sanh voi DB
        print(f"  loaded: id={art.id[:12]}... db_id={row['id'][:12]}... match={art.id == row['id']} | {row['title'][:60]}")
    return articles


def main() -> None:
    print("=" * 72)
    print("STEP 1 — Lay 8 bai gan day va check id-hash match voi DB")
    print("=" * 72)
    chunk = _load_recent_chunk(8)
    if not chunk:
        print("Khong co bai nao."); return

    client = get_groq_client()
    if not client:
        print("Thieu GROQ_API_KEY."); return

    print()
    print("=" * 72)
    print("STEP 2 — Triage 8B (id-keyed dict, anti-miss)")
    print("=" * 72)
    triage_map = triage_articles(chunk, client)
    print(f"  triage_map size = {len(triage_map)}")
    high = [a for a in chunk if triage_map.get(a.id, True)]
    print(f"  high_impact = {len(high)} bai (anti-miss policy)")

    if not high:
        print("Triage loai het. KHONG co gi de gui."); return

    print()
    print("=" * 72)
    print("STEP 3 — Analyze batch 70B (BatchOutcome + missing list)")
    print("=" * 72)
    outcome, missing = analyze_articles_batch(high, client)
    print(f"  outcome = {outcome} | missing = {len(missing)}/{len(high)}")
    success = outcome == "ok"

    print()
    print("=" * 72)
    print("STEP 4 — Trang thai TUNG bai sau khi analyze (in-memory)")
    print("=" * 72)
    actionable_count = 0
    for art in high:
        flag = "ACTIONABLE" if art.is_actionable else "skip"
        actionable_count += int(art.is_actionable)
        print(
            f"  [{flag:<10}] processed={art.processed} | impact={art.market_impact} "
            f"| sentiment={art.sentiment} | tokens={art.affected_tokens} "
            f"| takeaway={(art.key_takeaway or '')[:60]!r}"
        )
    print()
    print(f"==> Tong actionable trong chunk = {actionable_count} / {len(high)}")
    print("Neu actionable > 0 ma DB tg_sent van NULL trong production,")
    print("nghia la pipeline khong di toi nhanh send_telegram trong runtime.")


if __name__ == "__main__":
    main()
