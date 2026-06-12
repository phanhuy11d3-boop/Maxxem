---
name: cadence-check
description: Check the REAL cadence of the two-shift CryptoSentinel production — local Task Scheduler day shift + GH Actions 5.5h loop night shift — against the 30-minute stale window. Use when asking whether the pipeline is running on schedule, why price alerts expire stale, why the bot went quiet, or after editing the workflow schedule.
allowed-tools: Bash(py -3 .claude/skills/cadence-check/scripts/*)
context: fork
agent: ops-manager
---

# Cadence Check — two-shift coverage vs the 30-minute stale window

## Live analysis (computed deterministically before you read this)

```!
py -3 .claude/skills/cadence-check/scripts/check_cadence.py
```

## How to read the numbers (architecture since fae5dff, 2026-06-11)

Production runs in TWO shifts sharing one Supabase DB:

- **Day shift**: Windows Task Scheduler on the operator's PC, 1-min cadence,
  logs to `storage/local_cron.log`.
- **Night shift**: GH Actions `scraper.yml` — one run is a ~5h30 *shift* that
  loops the pipeline internally every minute (`timeout-minutes: 350`,
  concurrency group queues the next shift). A run staying `in_progress` for
  hours is HEALTHY; a scheduled run completing in 2–3 min means the shift
  loop died early — investigate that.

The script therefore measures timeline **coverage by activity intervals**
(both shifts), not gaps between GH run creation times. Do not recompute the
arithmetic — interpret it:

1. The output answers TWO different questions — report BOTH, never the verdict
   word alone:
   - *"Is the pipeline running right now?"* → `verdict` (scope = last 6h),
     `minutes_since_last_activity`, `gh_shift_active` / local shift alive.
   - *"Did we miss price moves in the window?"* → `coverage_pct_window` +
     `dead_air_gaps`. A `CADENCE OK` verdict with low 24h coverage means
     "healthy now, but moves WERE missed earlier today" — say exactly that.
2. Explain the consequence in CryptoSentinel terms: every `dead_air_gap` is a
   window where pair moves either were never scanned or their alerts expired
   stale (>30 min) before any run could dispatch them — they never reach
   Telegram. For a price-alert product, a missed window is a missed trade.
3. Call out any non-success runs listed.
4. If DEGRADED/BROKEN, say WHICH shift is failing:
   - `local_log` stale or missing while it's daytime (ICT) → check the
     `CryptoSentinel-Pipeline` scheduled task on the PC.
   - `gh_shift_active: no` and no recent GH activity → check whether the last
     shift ended and the queued one never started; a manual `workflow_dispatch`
     on `main` starts a new shift immediately.
   Do NOT propose re-architecting (loop vs VPS vs pinger) — that decision was
   closed by commit `fae5dff` (hybrid: local day shift + GH loop night shift).
5. If the script errored, report the error verbatim, not a guess. Notes: it
   uses the public GitHub REST API (no `gh` CLI — not installed on this
   machine); on rate-limit (HTTP 403) either wait or set `GITHUB_TOKEN`; repo
   slug is auto-derived from `git remote get-url origin`; local log timestamps
   are machine-local time and converted to UTC by the script.
