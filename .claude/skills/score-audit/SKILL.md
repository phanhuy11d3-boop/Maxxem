---
name: score-audit
description: Audit the deterministic conviction scores (confidence_score 0–100 + transmission_chain) attached to recent CryptoSentinel alerts. Use when confidence scores look flat/uninformative, after tuning config/dexscreener.yaml scoring.weights, or to check whether the score actually tracks alert quality.
allowed-tools: Bash(py -3 scripts/diagnose_scores.py*)
context: fork
agent: signal-analyst
---

# Score Audit — conviction layer calibration (read-only)

## Live distribution (computed deterministically before you read this)

```!
py -3 scripts/diagnose_scores.py
```

## How to read it

The conviction layer (`models/scoring.py`) blends 5 deterministic sub-scores —
magnitude, volume, pressure, alignment, liquidity — into one `confidence_score`
(0–100), plus a neutral `transmission_chain` evidence string. It is **display +
storage + premium routing only**: per the project doctrine *"thà noise còn hơn
miss"*, the score **never** suppresses the main channel. Every pair that crosses
a threshold is still sent.

Interpret, don't recompute:

1. **Is the score informative?** A healthy distribution spreads across bins. If
   p50 sits near 50 and p90 is low, every move scores the same — the layer adds
   no signal. Recommend re-weighting, not re-thresholding.
2. **Does it track quality?** Compare avg score by `tg_status`. If `sent` rows
   aren't scoring higher than `expired`, the score isn't capturing what reaches
   traders — worth investigating which sub-score dominates.
3. **Tuning lever:** only `config/dexscreener.yaml > scoring.weights` (and
   `premium_min_score`). **Never** change `thresholds_pct` / `min_volume_usd`
   here — those gate whether an alert fires at all and belong to threshold
   calibration, not scoring. Weights are auto-normalized to sum 1.0.
4. **premium_min_score:** raising it sends fewer alerts to PREMIUM_CHAT_ID (main
   channel unaffected); lowering it sends more. It does not gate anything.
5. If the script errored (e.g. DB port blocked in sandbox, `DATABASE_URL`
   missing), report the error verbatim — do not guess a distribution.
