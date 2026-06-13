---
name: telegram-render-audit
description: Read-only audit that verifies Telegram alert output matches backend signal fields such as confidence_score, market_cap, fdv, swap link, and cleaned symbols. Use when the channel output looks unchanged, missing, or out of sync with backend data.
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/run_render_alignment.py*)
context: fork
agent: notifier-broadcaster
shell: powershell
---

# Telegram Render Audit

Run the colocated alignment check:

```!
py -3 ${CLAUDE_SKILL_DIR}/scripts/run_render_alignment.py
```

Interpret:
- PASS means recent DB rows render every checked backend field.
- FAIL means a field exists in `signals` but the Telegram HTML dropped it.
- This is read-only: do not send Telegram from this skill.

