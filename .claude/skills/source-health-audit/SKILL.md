---
name: source-health-audit
description: Audit market-data source health and freshness. Use when the bot is quiet, DEX API errors appear, or a source may be stale/degraded.
arguments: [focus]
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/run_source_health_audit.py*)
context: fork
agent: source-resilience-engineer
shell: powershell
---

# Source Health Audit

Read-only unless the operator explicitly asks for a fix.

## Workflow

1. Run:
   ```!
   py -3 ${CLAUDE_SKILL_DIR}/scripts/run_source_health_audit.py
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
