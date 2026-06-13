---
name: threshold-backtest
description: Read-only threshold and pair/horizon pressure analysis from stored alerts. Use before tuning config/dexscreener.yaml thresholds.
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/run_threshold_backtest.py*)
context: fork
agent: signal-analyst
shell: powershell
---

# Threshold Backtest

```!
py -3 ${CLAUDE_SKILL_DIR}/scripts/run_threshold_backtest.py
```

Use the output to recommend per-pair overrides. This script currently analyzes
stored alerts only, so it cannot prove missed non-triggering moves.

Rules:
- Do not tune just to make the bot talk.
- Pair override beats global churn.
- Score weights are not threshold gates.
