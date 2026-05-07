"""
Goi 70B model truc tiep voi 5 bai gan day va in ket qua.
Muc tieu: xac dinh xem LLM co dang 'NEUTRAL hoa' moi thu hay khong.
"""
from __future__ import annotations
import os, sys, json, pathlib

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
from processors.insight_extractor import (
    get_groq_client, SYSTEM_PROMPT_BATCH, POWER_MODEL, FAST_MODEL, TRIAGE_PROMPT,
)


def main() -> None:
    # Lay 5 bai 'truong hop ro rang nen actionable' (ten BTC, hack, exchange...)
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, title, summary
            FROM articles
            WHERE processed = TRUE
              AND scraped_at > NOW() - INTERVAL '24 hours'
              AND (
                title ILIKE '%bitcoin%' OR title ILIKE '%coinbase%' OR
                title ILIKE '%hack%' OR title ILIKE '%fund%' OR title ILIKE '%ETF%'
              )
            ORDER BY scraped_at DESC LIMIT 5
            """
        )
        rows = cur.fetchall()
    conn.close()
    if not rows:
        print("Khong tim thay bai phu hop."); return

    client = get_groq_client()

    print("=" * 72)
    print("Goi 70B model truc tiep voi 5 bai 'ro rang co the actionable'")
    print("=" * 72)
    batch_input = [
        {"id": r["id"], "title": r["title"], "summary": (r["summary"] or "")[:500]}
        for r in rows
    ]
    print(f"  Input ({len(batch_input)} bai):")
    for b in batch_input:
        print(f"    - [{b['id'][:10]}] {b['title'][:80]}")

    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_BATCH},
            {"role": "user", "content": json.dumps(batch_input)},
        ],
        model=POWER_MODEL,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    print()
    print(f"  Raw response (first 1500 chars):\n{raw[:1500]}")
    print()

    data = json.loads(raw)
    results = data.get("results", [])
    print(f"  Da parse {len(results)} ket qua:")
    for r in results:
        impact = r.get("market_impact", "?")
        marker = "ACTIONABLE" if impact in ("bullish", "bearish") else "skip"
        print(
            f"    [{marker:<10}] impact={impact:<8} sent={r.get('sentiment','?')} | "
            f"id={r.get('id','?')[:10]} take={r.get('key_takeaway','')[:60]!r}"
        )

    # Triage check too
    print()
    print("=" * 72)
    print("So sanh: chay 8B triage")
    print("=" * 72)
    titles = [r["title"] for r in rows]
    triage_resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": TRIAGE_PROMPT},
            {"role": "user", "content": json.dumps(titles)},
        ],
        model=FAST_MODEL,
        response_format={"type": "json_object"},
    )
    raw2 = triage_resp.choices[0].message.content
    print(f"  Triage raw: {raw2}")


if __name__ == "__main__":
    main()
