---
name: source-integration-plan
description: Plan a new market-data source integration safely, including shadow mode, health telemetry, license/quota review, and promotion criteria.
arguments: [provider]
context: fork
agent: realtime-feed-researcher
---

# Source Integration Plan

Before adding a source, produce a plan with:

1. Provider, license/ToS, auth/quota requirements.
2. Coverage by chain/pair/address.
3. Normalized fields available vs `PairSnapshot`.
4. Failure modes: stale data, reconnect, rate limit, schema drift.
5. Shadow-mode design with no `signals` writes and no Telegram sends.
6. Promotion criteria and rollback.

Do not implement or enable the source until the operator approves the plan.
