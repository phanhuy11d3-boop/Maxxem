"""
scripts/daily_digest.py
=======================
Daily top-movers digest (LIVE-FIRE khi gửi). Bản tổng kết 24h các pair biến
động mạnh nhất — pattern leaderboard market-rank của Binance, nhưng 100% số liệu
từ signals đã ghi (không gọi lại API, không opinion).

Idempotent: 1 digest/ngày UTC, đánh dấu trong storage/digest_state.json. Chạy
lại trong ngày -> bỏ qua, trừ khi --force. KHÔNG đi qua outbox (digest không
phải price-alert nhạy giờ; stale-rule không áp dụng).

Dùng:
  py -3 scripts/daily_digest.py            # dry: in ra, KHÔNG gửi
  py -3 scripts/daily_digest.py --live     # LIVE-FIRE: gửi Telegram + ghi dấu ngày
  py -3 scripts/daily_digest.py --live --force   # gửi kể cả đã gửi hôm nay
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg2.extras import RealDictCursor  # noqa: E402

from storage.postgres import _get_pool  # noqa: E402
from utils.notifier import render_digest_html, send_digest  # noqa: E402

WINDOW_HOURS = 24
TOP_N = 10
DIGEST_STATE = ROOT / "storage" / "digest_state.json"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _already_sent_today() -> bool:
    try:
        state = json.loads(DIGEST_STATE.read_text(encoding="utf-8"))
        return state.get("last_digest_date") == _today_utc()
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _mark_sent_today() -> None:
    try:
        DIGEST_STATE.write_text(
            json.dumps({"last_digest_date": _today_utc()}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # ghi dấu fail không được làm sập (digest đã gửi rồi)
        print(f"[warn] không ghi được digest_state.json: {exc}")


def _fetch_top_movers() -> list[dict]:
    """Top pair theo |change_pct| trong 24h, distinct theo pair (lấy move mạnh nhất)."""
    conn = _get_pool().getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (chain_id, pair_address)
                       base_symbol, quote_symbol, chain_id, change_pct, horizon,
                       price_usd, volume_usd, confidence_score
                FROM signals
                WHERE observed_at > NOW() - INTERVAL '%s hours'
                ORDER BY chain_id, pair_address, ABS(change_pct) DESC
                """ % WINDOW_HOURS
            )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        _get_pool().putconn(conn)
    rows.sort(key=lambda r: abs(float(r.get("change_pct") or 0.0)), reverse=True)
    return rows[:TOP_N]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    live = "--live" in sys.argv
    force = "--force" in sys.argv

    if live and not force and _already_sent_today():
        print(f"Digest hôm nay ({_today_utc()}) đã gửi — bỏ qua (dùng --force để gửi lại).")
        return

    movers = _fetch_top_movers()
    ict = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=7))
    ).strftime("%Y-%m-%d %H:%M ICT")
    text = render_digest_html(movers, window_label=f"{WINDOW_HOURS}h", ict_label=ict)

    print("=" * 60)
    print(f"DAILY DIGEST ({'LIVE' if live else 'dry'}) — {len(movers)} pair")
    print("=" * 60)
    print(text)

    if not live:
        print("\n(dry) Thêm --live để gửi Telegram thật.")
        return

    if send_digest(text):
        _mark_sent_today()
        print("\n✅ Đã gửi digest + ghi dấu ngày.")
    else:
        print("\n❌ Gửi digest thất bại — KHÔNG ghi dấu (lần sau thử lại).")


if __name__ == "__main__":
    main()
