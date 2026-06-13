---
name: health-sweep
description: Run a full parallel health sweep of the CryptoSentinel pipeline — DEX scanner ingestion, signal-rule quality, database/outbox state, and Telegram delivery — by fanning out the four specialist subagents concurrently. Use when the pipeline looks degraded, the bot is silent, alerts look wrong, or before/after a deploy.
argument-hint: "[optional focus area, e.g. \"telegram\" or \"last 24h\"]"
---

# Parallel Health Sweep

You are the orchestrator. Fan the work out to the four specialist subagents and keep your own context clean: do NOT run the diagnostic scripts yourself — the subagents do, and only their summaries come back.

## Dispatch — all four Agent calls in ONE message so they run in parallel

Spawn each with `run_in_background: true`. Every task prompt MUST state: "READ-ONLY sweep: do not edit files, do not write to the DB, do not send Telegram messages. Return a structured report."

1. **ingestion-scout** — "Audit scanner health: run `py -3 scripts/diagnose_dexscreener.py`, read `config/dexscreener.yaml`, spot-check 1-2 pairs against the raw API with WebFetch (`https://api.dexscreener.com/latest/dex/pairs/<chain>/<addr>`). Report per-pair trigger/no-trigger, any [MISS]/[ERROR]/symbol-mismatch lines, and API availability."
2. **signal-analyst** — "Audit signal-rule quality: run `py -3 scripts/diagnose_dexscreener.py` and `py -3 scripts/diagnose_outbox.py` (both read-only). Compare alert volume in the signals table vs thresholds — too noisy (same pair firing every bucket) or suspiciously quiet (thresholds unreachable)? Report per-pair/horizon distribution and tuning suspicion."
3. **db-auditor** — "Audit DB and outbox state machine: run `py -3 scripts/diagnose_outbox.py`. Report tg_status distribution, 24h sent/expired counts, send-lag percentiles (any sent lag > 30 min or expired > 0 = delivery violation, report as BROKEN), queue depth, and any anomaly."
4. **notifier-broadcaster** — "Audit delivery path read-only: run `py -3 scripts/diagnose_outbox.py`, check signals are reaching tg_status='sent' within SLA (120s), render a dry preview via `py -3 models/pair_signal.py` (safe: no DB, no Telegram). Do NOT run `py -3 utils/notifier.py` — it sends a real Telegram message. Report formatting health and delivery latency."

If `$ARGUMENTS` names a focus area, still dispatch all four but tell the matching agent to go deeper on it.

## Required report format from each agent

- **Status**: OK / DEGRADED / BROKEN
- **Evidence**: script output numbers, not impressions
- **Suspected root cause** (if not OK)
- **Recommended fix** (do not apply it)

## Consolidate

When all four return, produce ONE report ordered by pipeline flow: scanner → rules → storage → delivery. Cross-correlate stages (e.g. "scanner triggered 6 signals + outbox shows 0 sent in 2h → delivery is the bottleneck, not the scanner"). Remember quiet can be healthy: "no pair crossed thresholds" with a healthy scanner is OK, not BROKEN. End with a prioritized fix list. Apply no fix without being asked.
