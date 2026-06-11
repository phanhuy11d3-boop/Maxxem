---
name: tg-status-vs-tg-sent-mismatch
description: articles table tracks delivery in two columns (tg_sent bool, tg_status text) that disagree (647 TRUE vs 581 'sent' on 2026-06-11); no 'expired' rows despite anti-stale rule
metadata:
  type: project
---

The `articles` table has two delivery-tracking columns that are not kept in sync: `tg_sent` (boolean, 647 TRUE on 2026-06-11) and `tg_status` (text outbox state, only 581 'sent', rest NULL — no 'pending'/'failed'/'expired' values observed). 66 rows were marked sent via `tg_sent` but never got `tg_status='sent'`, and stale unprocessed rows (5.6k as of 2026-06-11, oldest 2026-05-07) are never flagged `expired`.

**Why:** `tg_status` outbox appears to be a newer mechanism partially adopted alongside the legacy `tg_sent` boolean; older send paths only set the boolean.
**How to apply:** When auditing delivery, treat `tg_sent` as the authoritative legacy signal and `tg_status` as incomplete; do not conclude "66 unsent" from `tg_status` alone. Any fix should write both columns atomically (see `mark_processed_with_tg`) and add an expiry sweep for stale unprocessed rows. Related: [[diagnose-scripts-cp1252-crash]].
