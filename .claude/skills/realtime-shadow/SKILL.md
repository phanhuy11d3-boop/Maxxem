---
name: realtime-shadow
description: Inspect or operate realtime feed shadow mode. Shadow mode must not insert production signals or send Telegram.
argument-hint: "[status|plan|provider]"
---

# Realtime Shadow

Realtime feeds are research/canary until promoted. They must run with
`write_signals=false` and no Telegram side effects.

## Workflow

1. Read source configuration and docs.
2. Run read-only diagnostics if present:
   ```powershell
   py -3 scripts/diagnose_realtime_shadow.py
   py -3 scripts/diagnose_sources.py
   ```
3. Verify the source is marked shadow/canary, not primary.
4. Report coverage, freshness, errors, and promotion blockers.

## Promotion Checklist

- 3-7 days healthy source history.
- Covers pinned watchlist pairs.
- Has stale detection and reconnect/backoff.
- Cannot duplicate alerts across sources.
- Operator explicitly approves production promotion.
