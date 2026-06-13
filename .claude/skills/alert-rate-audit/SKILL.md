---
name: alert-rate-audit
description: Read-only audit of alert volume, queue pressure, and dispatch priority. Use when the channel feels spammy or Telegram delivery is backing up.
allowed-tools: Bash(py -3 scripts/diagnose_alert_rate.py*)
context: fork
agent: alert-rate-auditor
---

# Alert Rate Audit

```!
py -3 scripts/diagnose_alert_rate.py
```

Interpret:
- Fresh pending/failed >= 10 means backpressure risk.
- One pair/horizon dominating means tune that pair override first.
- Expired alerts are a delivery/cadence violation, not normal noise.

