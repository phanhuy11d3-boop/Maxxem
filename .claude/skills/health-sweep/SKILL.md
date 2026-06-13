---
name: health-sweep
description: Run a full parallel health sweep of the CryptoSentinel pipeline: source health, DEX scanner ingestion, signal-rule quality, database/outbox state, and Telegram delivery.
arguments: [focus]
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/run_health_sweep.py*)
context: fork
agent: ops-manager
shell: powershell
---

# Parallel Health Sweep

You are the orchestrator. Fan the work out to the specialist subagents and keep
your own context clean: do not run all diagnostics yourself. The subagents run
them and return summaries.

Every task prompt MUST state:

"READ-ONLY sweep: do not edit files, do not write to the DB, do not send
Telegram messages. Return a structured report."

Run the colocated deterministic sweep first so the report is grounded in one
repeatable command:

```!
py -3 ${CLAUDE_SKILL_DIR}/scripts/run_health_sweep.py
```

## Dispatch In Parallel

1. **source-resilience-engineer**
   "Audit source health: run
   `py -3 .claude/skills/source-health-audit/scripts/run_source_health_audit.py`.
   Report source status by source/chain, last_seen age, errors, and whether
   quiet is trustworthy."

2. **ingestion-scout**
   "Audit scanner health: run
   `py -3 .claude/skills/dexscreener-watchlist/scripts/run_watchlist_diagnosis.py`,
   read `config/dexscreener.yaml`, spot-check 1-2 pairs against the raw API with
   WebFetch (`https://api.dexscreener.com/latest/dex/pairs/<chain>/<addr>`).
   Report trigger/no-trigger, [MISS]/[ERROR]/symbol mismatch, and API availability."

3. **signal-analyst**
   "Audit signal-rule quality: run
   `py -3 .claude/skills/alert-rate-audit/scripts/run_alert_rate_audit.py`
   and `py -3 .claude/skills/score-audit/scripts/run_score_audit.py`.
   Report noisy pair/horizon distribution and tuning suspicion."

4. **db-auditor**
   "Audit DB and outbox state machine: run
   `py -3 .claude/skills/outbox-audit/scripts/run_outbox_audit.py`. Report
   tg_status distribution, sent/expired counts, send-lag percentiles, queue
   depth, and anomalies."

5. **notifier-broadcaster**
   "Audit delivery path read-only: run
   `py -3 .claude/skills/outbox-audit/scripts/run_outbox_audit.py` and
   `py -3 .claude/skills/telegram-render-audit/scripts/run_render_alignment.py`.
   Do NOT run `py -3 utils/notifier.py --live`."

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
