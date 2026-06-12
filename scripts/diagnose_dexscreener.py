"""Read-only DEXScreener scanner diagnosis.

Trả lời câu hỏi "bot im vì KHÔNG pair nào vượt ngưỡng, hay vì scanner hỏng?".
Fetch từng pair trong watchlist và in trigger/no-trigger với số liệu thật.
Không ghi DB, không gửi Telegram.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.pair_signal import HORIZONS
from scrapers.dexscreener import _entry_cfg, _num, _trigger, fetch_pair, load_config


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    print("=" * 72)
    print("DEXSCREENER WATCHLIST / THRESHOLD DIAGNOSIS")
    print("=" * 72)
    print(f"enabled              : {cfg.get('enabled')}")
    print(f"cooldown_minutes     : {cfg.get('cooldown_minutes')}")
    print(f"min_liquidity_usd    : {cfg.get('min_liquidity_usd')}")
    print(f"thresholds_pct       : {cfg.get('thresholds_pct')}")
    print(f"min_volume_usd       : {cfg.get('min_volume_usd')}")
    print(f"watchlist_count      : {len(cfg.get('watchlist') or [])}")
    print()

    triggered = 0
    for entry in cfg.get("watchlist") or []:
        name = entry.get("name") or entry.get("query") or entry
        if not (entry.get("chainId") and entry.get("pairAddress")):
            print(f"[WARN ] {name}: search-only entry — production phải pin chainId+pairAddress")
        try:
            pair = fetch_pair(entry)
        except Exception as exc:
            print(f"[ERROR] {name}: fetch failed: {exc}")
            continue
        if not pair:
            print(f"[MISS ] {name}: no pair returned (sai address hoặc symbol mismatch)")
            continue

        liquidity = _num((pair.get("liquidity") or {}).get("usd"))
        volume = pair.get("volume") or {}
        price_change = pair.get("priceChange") or {}
        hit = _trigger(pair, _entry_cfg(entry, cfg))
        if hit:
            triggered += 1
            horizon, change = hit
            verdict = f"TRIGGER {horizon} {change:+.2f}%"
        else:
            verdict = "no trigger"
        label = (
            f"{(pair.get('baseToken') or {}).get('symbol')}/"
            f"{(pair.get('quoteToken') or {}).get('symbol')}"
        )
        changes = " ".join(f"{h}={_num(price_change.get(h)):+.2f}%" for h in HORIZONS)
        vols = " ".join(f"{h}=${_num(volume.get(h)):,.0f}" for h in HORIZONS)
        print(f"[{verdict:<20}] {name} -> {label} | liq=${liquidity:,.0f} | {changes} | {vols}")

    print()
    print(f"triggered_count      : {triggered}")
    print("Lưu ý: triggered ở đây chưa qua dedup cooldown — pipeline thật có thể")
    print("đã gửi alert này trong bucket hiện tại nên không gửi lại.")


if __name__ == "__main__":
    main()
