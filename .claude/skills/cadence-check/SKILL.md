---
name: cadence-check
description: Check the REAL GitHub Actions cadence of scraper.yml against the 1-minute target and the 30-minute stale window. Use when asking whether the pipeline is running on schedule, why articles die stale, why the bot went quiet, or after editing the workflow schedule.
allowed-tools: Bash(py -3 .claude/skills/cadence-check/scripts/*)
context: fork
agent: ops-manager
---

# Cadence Check — GH Actions vs the 1-minute target

## Live analysis (computed deterministically before you read this)

```!
py -3 .claude/skills/cadence-check/scripts/check_cadence.py
```

## Your task

The numbers and the verdict above come from `scripts/check_cadence.py` — do not recompute them. Your job is to interpret:

1. State the verdict first (`CADENCE OK` / `DEGRADED` / `BROKEN`) with the key numbers: median/max gap, time since last scheduled run, `timeline_uncovered_pct`.
2. Explain the consequence in CryptoSentinel terms: every gap beyond 30 minutes is dead air where new articles expire stale and join the unprocessed backlog (~5k rows as of 2026-06).
3. Call out any non-success runs listed.
4. If DEGRADED/BROKEN, remind the operator of the open decision (loop-inside-workflow vs VPS cron vs external workflow_dispatch pinger) — do NOT pick or implement one unless asked.
5. If the script errored, report the error verbatim, not a guess. Notes: it uses the public GitHub REST API (no `gh` CLI — not installed on this machine); on rate-limit (HTTP 403) either wait or set `GITHUB_TOKEN`; repo slug is auto-derived from `git remote get-url origin`.
