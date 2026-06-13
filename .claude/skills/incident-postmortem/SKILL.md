---
name: incident-postmortem
description: Produce a structured postmortem for source degradation, expired alerts, send-lag SLA breaches, duplicate sends, or unexpected quiet periods.
argument-hint: "[incident window/focus]"
---

# Incident Postmortem

Run read-only diagnostics first:

```powershell
py -3 scripts/diagnose_sources.py
py -3 scripts/diagnose_dexscreener.py
py -3 scripts/diagnose_outbox.py
py -3 scripts/diagnose_alert_rate.py
```

Report:
- Incident window
- User impact
- Source/scanner/storage/delivery evidence
- Root cause
- What prevented worse impact
- Follow-up fixes

Do not edit files during the postmortem unless separately asked.

