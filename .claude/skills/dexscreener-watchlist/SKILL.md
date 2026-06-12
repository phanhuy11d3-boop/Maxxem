---
name: dexscreener-watchlist
description: Add, remove, tune, or diagnose DEXScreener pair price-move alerts. Use when CryptoSentinel should post direct coin/pair pump-dump movement alerts, when alerts are too quiet/noisy, or when editing config/dexscreener.yaml.
argument-hint: "[pair/query/threshold change]"
---

# DEXScreener Watchlist

Direct DEX pair movement is THE product. `scrapers/dexscreener.py` creates
`PairSignal` objects deterministically from DEXScreener pair metrics — no LLM
touches anything in this path.

## Source of Truth

- Watchlist and thresholds: `config/dexscreener.yaml`
- Scanner: `scrapers/dexscreener.py`
- Data contract + Telegram render: `models/signal.py`
- Read-only diagnosis: `scripts/diagnose_dexscreener.py`
- Tests: `tests/unit/test_dexscreener_scanner.py`, `tests/unit/test_signal_format.py`

## Procedure

1. Run the read-only diagnosis first:
   ```powershell
   py -3 scripts/diagnose_dexscreener.py
   ```
2. If adding a pair, follow the `add-source` skill (validate via live API, then
   pin). Every production entry must include `chainId`, `pairAddress`,
   `baseSymbol`, and `quoteSymbol`.
3. Tune in this order, preferring per-pair overrides over global churn:
   - `min_liquidity_usd`
   - `min_volume_usd` per horizon
   - `thresholds_pct` per horizon
   - `cooldown_minutes`
4. Keep alerts direct and numeric. Required evidence in every alert: pair,
   horizon, price-change %, price, multi-horizon row, volume, liquidity,
   buys/sells, chain/DEX, and DEXScreener link.
5. Verify:
   ```powershell
   py -3 -m pytest tests/unit -q
   py -3 scripts/diagnose_dexscreener.py
   ```

## Guardrails

- Do not lower thresholds just to make the bot talk; report "no pair crossed thresholds" as a healthy quiet state.
- Do not leave production watchlist entries search-only; search can resolve the wrong token/pair.
- Do not add illiquid pairs unless the operator explicitly asks for meme/new-pair hunting.
- Do not edit Telegram delivery state or run live-fire Telegram tests from this skill.
- If DEXScreener API fails, scanner must return `[]` and log warning; pipeline must continue.
- Never add sentiment, bullish/bearish labels, or AI commentary to the alert format.
