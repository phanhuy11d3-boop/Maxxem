"""
unstick_retry.py
================
One-shot util: reset retry_count cho cac bai unprocessed bi treo (>= MAX_RETRY).

Ly do: Trong 24h gan day, tat ca 21 bai stuck deu cung 1 nguon (CoinDesk),
goi y la LLM tra ve ID bi truncate/sai format chu khong phai bai do co van de.
Sau khi siet prompt + bo sung positional fallback (insight_extractor.py), can
reset retry_count de pipeline thu lai mot lan nua.

Chay 1 lan duy nhat sau khi deploy fix moi:
    py scripts/unstick_retry.py
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
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT source, COUNT(*) AS n
                   FROM articles
                   WHERE processed = FALSE AND retry_count >= 3
                   GROUP BY source ORDER BY n DESC"""
            )
            stuck = cur.fetchall()
            if not stuck:
                print("Khong co bai nao bi treo retry."); return
            print("Truoc khi reset:")
            for r in stuck:
                print(f"  {r['source']:<22} : {r['n']}")

            cur.execute(
                """UPDATE articles SET retry_count = 0
                   WHERE processed = FALSE AND retry_count >= 3
                   RETURNING id, source"""
            )
            updated = cur.fetchall()
        conn.commit()
        print(f"\nDa reset retry_count = 0 cho {len(updated)} bai.")
        print("Pipeline lan chay tiep theo se thu phan tich lai chung.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
