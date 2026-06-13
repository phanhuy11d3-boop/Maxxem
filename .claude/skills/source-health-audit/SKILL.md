---
name: source-health-audit
description: Audit market-data source health and freshness. Use when the bot is quiet, DEX API errors appear, or a source may be stale/degraded.
argument-hint: "[optional source/chain focus]"
---

# Source Health Audit

Read-only unless the operator explicitly asks for a fix.

## Workflow

1. Run:
   ```powershell
   py -3 scripts/diagnose_sources.py
   py -3 scripts/diagnose_dexscreener.py
   py -3 scripts/diagnose_outbox.py
   ```
2. Interpret in pipeline order:
   - source health: healthy / degraded / unhealthy
   - scanner: trigger / no trigger / API error / symbol mismatch
   - outbox: sent / pending / failed / expired
3. Report whether quiet is trustworthy.

## Verdict Rules

- Healthy source + no trigger = OK quiet.
- Degraded/unhealthy source + no trigger = not trustworthy.
- Scanner triggered + outbox not sent = delivery problem, not source problem.

