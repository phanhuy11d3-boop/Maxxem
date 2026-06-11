---
name: health-sweep
description: Run a full parallel health sweep of the CryptoSentinel pipeline — ingestion, LLM signal quality, database/outbox state, and Telegram delivery — by fanning out the four specialist subagents concurrently. Use when the pipeline looks degraded, the bot is silent, signals look wrong, or before/after a deploy.
argument-hint: "[optional focus area, e.g. \"telegram\" or \"last 36h\"]"
---

# Parallel Health Sweep

You are the orchestrator. Fan the work out to the four specialist subagents and keep your own context clean: do NOT run the diagnostic scripts yourself — the subagents do, and only their summaries come back.

## Dispatch — all four Agent calls in ONE message so they run in parallel

Spawn each with `run_in_background: true`. Every task prompt MUST state: "READ-ONLY sweep: do not edit files, do not write to the DB, do not send Telegram messages. Return a structured report."

1. **ingestion-scout** — "Audit ingestion health: read `config/sources.yaml`, spot-check 2-3 feeds with WebFetch for availability and parse-ability, check scrapers for recent breakage signals. Report per-source status."
2. **signal-analyst** — "Audit signal quality: run `py -3 scripts/diagnose_recent.py` and `py -3 scripts/diagnose_pipeline.py` (both read-only). Look for neutral-drift, triage misclassification, stuck retries. Do NOT run unstick_retry.py."
3. **db-auditor** — "Audit DB and outbox state machine: run `py -3 scripts/diagnose_telegram.py`, `py -3 scripts/audit_agent.py`, `py -3 scripts/query_recent_non_neutral.py --limit 10 --max-age-minutes 30`. Report counts of pending/sent/failed/expired, the delivery-latency percentiles from section 7 (any sent row > 30 min or `expired` > 0 = delivery violation, report as BROKEN), and any anomaly."
4. **notifier-broadcaster** — "Audit delivery path read-only: run `py -3 scripts/diagnose_telegram2.py`, check that actionable rows are reaching `tg_sent`. Do NOT run diagnose_marktg.py (it live-fires)."

If `$ARGUMENTS` names a focus area, still dispatch all four but tell the matching agent to go deeper on it.

## Required report format from each agent

- **Status**: OK / DEGRADED / BROKEN
- **Evidence**: script output numbers, not impressions
- **Suspected root cause** (if not OK)
- **Recommended fix** (do not apply it)

## Consolidate

When all four return, produce ONE report ordered by pipeline flow: ingestion → analysis → storage → delivery. Cross-correlate stages (e.g. "DB shows 40 pending + broadcaster shows 0 sent in 2h → delivery is the bottleneck, not analysis"). End with a prioritized fix list. Apply no fix without being asked.
