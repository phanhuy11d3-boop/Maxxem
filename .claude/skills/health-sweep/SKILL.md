---
name: health-sweep
description: Run a full parallel health sweep of the CryptoSentinel pipeline: source health, DEX scanner ingestion, signal-rule quality, database/outbox state, and Telegram delivery.
argument-hint: "[optional focus area, e.g. source, telegram, last 24h]"
---

# Parallel Health Sweep

You are the orchestrator. Fan the work out to the specialist subagents and keep
your own context clean: do not run all diagnostics yourself. The subagents run
them and return summaries.

Every task prompt MUST state:

"READ-ONLY sweep: do not edit files, do not write to the DB, do not send
Telegram messages. Return a structured report."

## Dispatch In Parallel

1. **source-resilience-engineer**
   "Audit source health: run `py -3 scripts/diagnose_sources.py` and
   `py -3 scripts/diagnose_dexscreener.py`. Report source status by source/chain,
   last_seen age, errors, and whether quiet is trustworthy."

2. **ingestion-scout**
   "Audit scanner health: run `py -3 scripts/diagnose_dexscreener.py`, read
   `config/dexscreener.yaml`, spot-check 1-2 pairs against the raw API with
   WebFetch (`https://api.dexscreener.com/latest/dex/pairs/<chain>/<addr>`).
   Report trigger/no-trigger, [MISS]/[ERROR]/symbol mismatch, and API availability."

3. **signal-analyst**
   "Audit signal-rule quality: run `py -3 scripts/diagnose_dexscreener.py`,
   `py -3 scripts/diagnose_outbox.py`, and `py -3 scripts/diagnose_alert_rate.py`.
   Report noisy pair/horizon distribution and tuning suspicion."

4. **db-auditor**
   "Audit DB and outbox state machine: run `py -3 scripts/diagnose_outbox.py`.
   Report tg_status distribution, sent/expired counts, send-lag percentiles,
   queue depth, and anomalies."

5. **notifier-broadcaster**
   "Audit delivery path read-only: run `py -3 scripts/diagnose_outbox.py`; render
   a dry preview via `py -3 models/pair_signal.py`. Do NOT run
   `py -3 utils/notifier.py --live`."

If `$ARGUMENTS` names a focus area, still dispatch all agents but tell the
matching agent to go deeper.

## Required Agent Report

- Status: OK / DEGRADED / BROKEN
- Evidence: script output numbers
- Suspected root cause if not OK
- Recommended fix, not applied

## Consolidate

Produce one report ordered by pipeline flow:

source health -> scanner -> rules -> storage -> delivery

Quiet is healthy only when source health and scanner fetches are healthy. End
with a prioritized fix list. Apply no fix without being asked.
