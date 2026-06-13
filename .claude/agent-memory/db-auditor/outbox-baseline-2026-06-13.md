---
name: outbox-baseline-2026-06-13
description: Healthy outbox baseline as of 2026-06-13 — all 23 signals sent, zero expired/failed/pending, p95 lag 4s
metadata:
  type: project
---

Audit date: 2026-06-13 (post DEX-only pivot, signals table).

**Status: OK**

tg_status distribution (all-time):
- sent: 23
- no other states present

KPI 24h:
- sent_24h: 23
- expired_24h: 0
- in_queue (pending + failed): 0
- send lag p50: 0s, p95: 4s

State machine: every row followed pending -> sent in exactly 1 attempt. No row has tg_attempts > 1. No tg_last_error on any row.

Minor observation: two rows show tg_sent_at 1s before observed_at (sub-second clock skew between app clock and DB NOW()); not a real violation.

**Why:** First clean baseline after 2026-06-12 DEX-only refactor. Old articles-era baseline discarded.

**How to apply:** Future audits should compare against these numbers. If expired_24h > 0 or any sent row has lag > 1800s, report BROKEN. If in_queue > 0 and not draining within one scanner cadence cycle, investigate claim_tg_send_slot or scheduler.

Related: [[env-console-cp1252]] — always run diagnose_outbox.py with PYTHONIOENCODING=utf-8.
Also: DATABASE_URL is not auto-loaded in bash; must `source .env` before running any diagnose script.
