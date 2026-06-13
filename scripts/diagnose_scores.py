"""Read-only conviction-score diagnosis cho bảng signals.

In phân bố confidence_score (min/p50/p90/max), tỷ lệ điểm thấp, tương quan
score ↔ đã gửi, và mẫu transmission_chain gần nhất. Giúp signal-analyst phát
hiện trọng số lệch (vd mọi alert đều ~50 = scoring không phân biệt được).

Không UPDATE/INSERT — an toàn chạy bất kỳ lúc nào trên production DB.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._env import load_dotenv_if_present  # noqa: E402

load_dotenv_if_present(ROOT)

from psycopg2.extras import RealDictCursor

from models.pair_signal import clean_symbol
from storage.postgres import _get_pool  # noqa: E402

WINDOW_HOURS = 72


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 72)
            print(f"CONVICTION SCORE DIAGNOSIS (read-only, last {WINDOW_HOURS}h)")
            print("=" * 72)

            cur.execute(
                """
                SELECT
                  COUNT(*) AS total,
                  COUNT(confidence_score) AS scored,
                  COALESCE(MIN(confidence_score), 0) AS min_s,
                  COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY confidence_score), 0) AS p50_s,
                  COALESCE(PERCENTILE_CONT(0.9) WITHIN GROUP (
                    ORDER BY confidence_score), 0) AS p90_s,
                  COALESCE(MAX(confidence_score), 0) AS max_s,
                  COALESCE(AVG(confidence_score), 0) AS avg_s
                FROM signals
                WHERE observed_at > NOW() - INTERVAL '%s hours'
                """ % WINDOW_HOURS
            )
            row = cur.fetchone() or {}
            total = int(row.get("total") or 0)
            scored = int(row.get("scored") or 0)
            print("\n-- Phân bố confidence_score --")
            if scored == 0:
                print("  (chưa có signal nào có điểm — scoring mới bật hoặc DB trống)")
            else:
                print(f"  signals   : {total} ({scored} có điểm, {total - scored} NULL/cũ)")
                print(f"  min       : {row['min_s']:.0f}")
                print(f"  p50       : {row['p50_s']:.0f}")
                print(f"  p90       : {row['p90_s']:.0f}")
                print(f"  max       : {row['max_s']:.0f}")
                print(f"  avg       : {row['avg_s']:.1f}")

            # Histogram thô theo tier 10 điểm
            cur.execute(
                """
                SELECT (confidence_score / 10) * 10 AS tier, COUNT(*) AS n
                FROM signals
                WHERE confidence_score IS NOT NULL
                  AND observed_at > NOW() - INTERVAL '%s hours'
                GROUP BY tier ORDER BY tier
                """ % WINDOW_HOURS
            )
            rows = cur.fetchall()
            if rows:
                print("\n-- Histogram (bin 10 điểm) --")
                peak = max(int(r["n"]) for r in rows) or 1
                for r in rows:
                    n = int(r["n"])
                    bar = "█" * max(1, round(n / peak * 30))
                    print(f"  {int(r['tier']):>3}-{int(r['tier'])+9:<3} | {bar} {n}")

            # Tương quan score ↔ đã gửi (chất lượng điểm có khớp delivery không)
            cur.execute(
                """
                SELECT tg_status,
                       COUNT(*) AS n,
                       COALESCE(AVG(confidence_score), 0) AS avg_s
                FROM signals
                WHERE confidence_score IS NOT NULL
                  AND observed_at > NOW() - INTERVAL '%s hours'
                GROUP BY tg_status ORDER BY n DESC
                """ % WINDOW_HOURS
            )
            rows = cur.fetchall()
            if rows:
                print("\n-- Score trung bình theo trạng thái gửi --")
                for r in rows:
                    print(f"  {r['tg_status'] or 'NULL':<10} : n={int(r['n']):<4} avg_score={r['avg_s']:.1f}")

            # Mẫu transmission_chain gần nhất
            cur.execute(
                """
                SELECT base_symbol, quote_symbol, horizon, change_pct,
                       confidence_score, transmission_chain, observed_at
                FROM signals
                WHERE confidence_score IS NOT NULL
                ORDER BY observed_at DESC LIMIT 10
                """
            )
            rows = cur.fetchall()
            if rows:
                print("\n-- 10 signal có điểm gần nhất --")
                for r in rows:
                    pair = (
                        f"{clean_symbol(r['base_symbol']).upper()}/"
                        f"{clean_symbol(r['quote_symbol']).upper()}"
                    )
                    print(
                        f"  {r['observed_at']:%m-%d %H:%M} "
                        f"{pair} "
                        f"{r['change_pct']:+.1f}% {r['horizon']} "
                        f"score={r['confidence_score']} · {r['transmission_chain'] or '-'}"
                    )

            print("\n-- Đọc kết quả --")
            print("  • p50 dồn quanh 50 + p90 thấp = scoring không phân biệt → cân lại weights.")
            print("  • avg score 'sent' không cao hơn 'expired' = điểm chưa phản ánh chất lượng.")
            print("  • Điều chỉnh ở config/dexscreener.yaml > scoring.weights (KHÔNG đụng thresholds).")
    finally:
        _get_pool().putconn(conn)


if __name__ == "__main__":
    main()
