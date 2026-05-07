"""
Test mark_tg_sent va send_telegram tren 1 bai actionable trong DB.
Day la THUC SU goi API + UPDATE de xem lieu trong production con hoat dong khong.
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
from models.article import Article, MarketImpact, normalize_market_impact
from storage.postgres import mark_tg_sent
from utils.notifier import send_telegram


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT * FROM articles
               WHERE processed = TRUE
                 AND market_impact IN ('bullish','bearish')
                 AND tg_sent IS NULL
               ORDER BY scraped_at DESC LIMIT 1"""
        )
        row = cur.fetchone()
    if not row:
        print("Khong co bai actionable nao chua gui.")
        return

    print("=" * 72)
    print("Bai du dinh test:")
    print("=" * 72)
    print(f"  id           : {row['id'][:16]}...")
    print(f"  source       : {row['source']}")
    print(f"  market_impact: {row['market_impact']}")
    print(f"  tg_sent (DB) : {row['tg_sent']}")
    print(f"  title        : {row['title']}")

    art = Article(
        url=row["url"], title=row["title"], source=row["source"],
        published_at=row["published_at"], summary=row["summary"],
        scraped_at=row["scraped_at"], sentiment=row["sentiment"],
        market_impact=normalize_market_impact(row["market_impact"]),
        key_takeaway=row["key_takeaway"],
        narrative_tag=row.get("narrative_tag"),
        affected_tokens=row.get("affected_tokens"),
        urgency=row.get("urgency"),
        processed=True,
    )

    print(f"\n  in-memory id : {art.id[:16]}...  match={art.id == row['id']}")
    print(f"  is_actionable: {art.is_actionable}")
    print(f"  format_telegram_html len={len(art.format_telegram_html())}")

    print()
    print("=" * 72)
    print("Test 1: mark_tg_sent voi gia tri test (KHONG goi API Telegram)")
    print("=" * 72)
    # Goi mark_tg_sent voi True de thu nghiem update DB
    print("  Goi mark_tg_sent(id, True)...")
    mark_tg_sent(art.id, True)

    # Kiem tra ket qua
    conn2 = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    with conn2.cursor(cursor_factory=RealDictCursor) as cur2:
        cur2.execute("SELECT tg_sent FROM articles WHERE id = %s", (art.id,))
        new_val = cur2.fetchone()
    conn2.close()
    print(f"  DB tg_sent SAU khi goi mark_tg_sent(True): {new_val['tg_sent']}")
    if new_val["tg_sent"] is True:
        print("  >>> mark_tg_sent HOAT DONG BINH THUONG. Dat lai NULL.")
    else:
        print("  >>> CO LOI: mark_tg_sent KHONG cap nhat duoc DB!")

    # Reset ve NULL de khong gay nhieu data
    conn3 = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    with conn3.cursor() as cur3:
        cur3.execute("UPDATE articles SET tg_sent = NULL WHERE id = %s", (art.id,))
    conn3.commit()
    conn3.close()
    print("  -> da reset tg_sent ve NULL")

    conn.close()


if __name__ == "__main__":
    main()
