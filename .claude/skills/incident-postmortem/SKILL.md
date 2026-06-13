---
name: incident-postmortem
description: Produce a structured postmortem for source degradation, expired alerts, send-lag SLA breaches, duplicate sends, or unexpected quiet periods.
arguments: [incident]
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/collect_evidence.py*)
context: fork
agent: ops-manager
shell: powershell
---

# Incident Postmortem

Run read-only diagnostics first:

```!
py -3 ${CLAUDE_SKILL_DIR}/scripts/collect_evidence.py
```

Report:
- Incident window
- User impact
- Source/scanner/storage/delivery evidence
- Root cause
- What prevented worse impact
- Follow-up fixes

Do not edit files during the postmortem unless separately asked.
