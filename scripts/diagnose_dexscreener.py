"""Read-only DEXScreener scanner diagnosis.

Fetches configured watchlist pairs and prints whether each pair crosses the
current alert thresholds. Does not write DB and does not send Telegram.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapers.dexscreener import HORIZONS, _num, _trigger, fetch_pair, load_config


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
    print(f"watchlist_count      : {len(cfg.get('watchlist') or [])}")
    print()

    triggered = 0
    for entry in cfg.get("watchlist") or []:
        name = entry.get("name") or entry.get("query") or entry
        try:
            pair = fetch_pair(entry)
        except Exception as exc:
            print(f"[ERROR] {name}: fetch failed: {exc}")
            continue
        if not pair:
            print(f"[MISS ] {name}: no pair returned")
            continue

        liquidity = _num((pair.get("liquidity") or {}).get("usd"))
        volume = pair.get("volume") or {}
        price_change = pair.get("priceChange") or {}
        hit = _trigger(pair, cfg)
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


if __name__ == "__main__":
    main()
