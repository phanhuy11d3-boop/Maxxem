---
name: outbox-audit
description: Read-only audit of the Telegram outbox state machine, including sent/failed/pending/expired counts, send lag, retry attempts, and stale delivery risk. Use when alerts are missing, delayed, duplicated, or suspected of failing silently.
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/run_outbox_audit.py*)
context: fork
agent: db-auditor
shell: powershell
---

# Outbox Audit

Run the colocated outbox check:

```!
py -3 ${CLAUDE_SKILL_DIR}/scripts/run_outbox_audit.py
```

Interpret:
- `pending` or `failed` rows that stay fresh indicate dispatch pressure.
- `expired` rows in the last 24h indicate cadence or delivery failure.
- A sent row with high lag is a latency/SLA issue, not a source issue.

