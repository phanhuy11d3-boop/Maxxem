---
name: gh-actions-cadence-observed
description: GH Actions cron throttling baseline and the two-shift mitigation (closed by fae5dff) — what healthy vs broken looks like per shift
metadata:
  type: project
---

GitHub Actions does NOT honor the 1-minute cron for repo phanhuy11d3-boop/Maxxem. Baseline measured 2026-06-11 (UTC): median scheduled-run gap ~149-152 min, max 267 min, 100% of gaps over the 30-min stale window. This is free-tier scheduler throttling, not pipeline failure — all runs themselves succeeded.

**Decision CLOSED by commit `fae5dff` (2026-06-11): hybrid two-shift architecture.** Do not re-propose loop-vs-VPS-vs-pinger alternatives.

- **Day shift**: Windows Task Scheduler (`CryptoSentinel-Pipeline`) on operator PC, 1-min cadence, logs to `storage/local_cron.log` (timestamps machine-local, ICT = UTC+7).
- **Night shift**: GH Actions `scraper.yml` — one run is a ~5h30 shift looping the pipeline internally every minute (`timeout-minutes: 350`, concurrency group queues next shift). A run staying `in_progress` for hours is HEALTHY; a scheduled run completing in 2-3 min means the shift loop died early.
- Commit `695bd1c`: 70B free tier hits daily token cap mid-night-shift; 8B failover added.

**Handover gap fix (commit `0fa17da`, 2026-06-11):** final step of each GH shift self-dispatches the next shift via `workflow_dispatch` API. Repo secret `WORKFLOW_PAT` (fine-grained PAT, Actions: read+write on Maxxem) added and verified 2026-06-11 ~08:35 UTC — manual dispatch with it returned 204, run 27334466511 queued behind the live shift; the chain is active. If shifts stop self-chaining in the future, check PAT expiration first (403 with `x-accepted-github-permissions: actions=write` = missing/insufficient PAT). Loop step has its own `timeout-minutes: 340` so the dispatch step still runs if the loop hangs.

**How to apply:** Diagnose by shift, not by re-architecting. Weak spot observed 2026-06-11: the shift handover zone (~23:00-01:00 UTC / 06:00-08:00 ICT) produced a 115-min dead-air gap — GH shift ended and the local day shift / queued GH shift didn't pick up promptly. First-day coverage with both shifts: 32% of 24h window, so throttling still dominates between GH shifts. A manual `workflow_dispatch` on `main` starts a new GH shift immediately. A `workflow_dispatch` run showing `cancelled` immediately before another dispatch (seen 06-11 03:12 -> 03:18 UTC) is the concurrency group superseding the old shift — normal, not a failure. Cadence script uses public REST API (no `gh` CLI on this machine); HTTP 403 = rate limit, set `GITHUB_TOKEN`.
