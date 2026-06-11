---
name: outbox-baseline-2026-06-10
description: Known-healthy outbox baselines (last clean audit 2026-06-11) — 66 legacy tg_status=NULL rows, ~5.6k unprocessed backlog explained, 647/647 sent
metadata:
  type: project
---

Known baselines — do not re-flag these as anomalies:

1. **66 legacy rows with `tg_sent=TRUE` but `tg_status=NULL`** — sent before the outbox migration introduced `tg_status`. Masked by COALESCE in queries. Not a new bug; only worry if this count grows. (Still exactly 66 on 2026-06-11.)
2. **Backlog of unprocessed rows with `retry_count=0`** — consequence of the stale-30-minute rule plus sparse GitHub Actions cadence: articles age past 30 min before a run picks them up, so they are intentionally skipped. These are NOT stuck rows. (5161 on 2026-06-10; 5606 on 2026-06-11 — grows steadily, expected.)
3. **Last-seen healthy counts (2026-06-11):** total 7219 rows, 1613 processed; impact split neutral 966 / bullish 335 / bearish 312; actionable 647 with **647/647 sent OK, 0 failed, 0 stuck retry>=3, 0 stale pending**. tg_status breakdown: sent 581, pending/failed/expired 0, NULL 6638 (unprocessed+neutral+66 legacy). Triage: 220 skipped by 8B, 746 analyzed-to-neutral by 70B, 647 actionable.
   (Previous 2026-06-10: total 6688, 1527 processed, 595/595 sent.)

**Why:** Avoids re-discovering that these patterns are benign each audit; the real signals are deviations from these numbers (failed>0, retry>=3 stuck rows, actionable-but-unsent>0, legacy-NULL count above 66).

**How to apply:** Compare fresh `scripts/diagnose_telegram.py` output against these counts. Remember [[env-console-cp1252]] when running it. Update this file with new healthy counts after each clean audit.
