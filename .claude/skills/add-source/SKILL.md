---
name: add-source
description: Add a new watched DEX pair (price-data source) to the CryptoSentinel watchlist following the full validation procedure — resolve the real pairAddress, verify liquidity and symbols against the live DEXScreener API, then pin it in config/dexscreener.yaml.
arguments: [chain, pair]
shell: powershell
---

# Add Source — watched DEX pair procedure

A "source" in CryptoSentinel v3 is a watched pair on DEXScreener. Adding one is
NOT just editing `config/dexscreener.yaml`: a wrong `pairAddress` means every
future alert lies about the token. Validate first, pin exactly, then verify.

## 1. Validate the pair against the live API

```powershell
py -3 .claude/skills/add-source/scripts/validate_pair.py <chain> <pairAddress>
# or discover candidates first:
py -3 .claude/skills/add-source/scripts/validate_pair.py --search "WIF/SOL"
```

The script prints verdict GOOD/WARN/BAD with real liquidity, volume, and the
actual base/quote symbols the API returns. Only proceed on `GOOD`. On `WARN`
(low liquidity) ask the operator; on `BAD` stop — do not add a dead or fake pair.

`--search` lists the top-liquidity matching pairs so you can pick the canonical
pool. NEVER ship a search-only entry to production.

## 2. Add to config/dexscreener.yaml

Every production entry must pin ALL four identity fields:

```yaml
  - name: "WIF/SOL"
    query: "WIF/SOL"            # chỉ dùng cho diagnose/khám phá
    chainId: "solana"
    pairAddress: "<address từ bước 1>"
    baseSymbol: "WIF"           # phải khớp symbol API trả về
    quoteSymbol: "SOL"
```

Optional per-pair overrides when the pair's volatility profile differs from the
global defaults: `thresholds_pct`, `min_volume_usd`, `min_liquidity_usd`.

## 3. Verify the scanner sees it

```powershell
py -3 .claude/skills/dexscreener-watchlist/scripts/run_watchlist_diagnosis.py
```

The new pair must appear with real numbers (not `[MISS]`). A symbol mismatch
prints an error and the pair is skipped — fix the config, don't bypass the guard.

## 4. Run the unit suite

```powershell
py -3 -m pytest tests/unit -q
```

## 5. Report

Pair name, chain, pinned address, validation verdict (liquidity/volume numbers),
any per-pair overrides chosen and why, diagnosis line, test result.
