# Realtime Resilience Refactor

This refactor makes the scanner source-agnostic without changing the product:
DEX-only, numeric price-move alerts, no news, no LLM commentary.

## Implemented Spine

1. Source contracts in `sources/base.py`.
2. DEXScreener REST adapter in `sources/dexscreener_rest.py`.
3. Normalization in `sources/normalize.py`.
4. Trigger engine in `signals/engine.py`.
5. Source health table and diagnostics.
6. Outbox dispatch priority for backpressure.
7. Agent/skill expansion for source health and alert-rate operations.

## Realtime Policy

Realtime feeds are not production by default. They must:

- run in shadow mode first;
- write no production `signals`;
- send no Telegram messages;
- expose health/freshness;
- prove coverage and stability before promotion.

## Promotion Criteria

- 3-7 days healthy source history.
- Pinned watchlist coverage.
- Clear stale detection and reconnect/backoff.
- Cross-source duplicate policy.
- Explicit operator approval.

## Verification

```powershell
py -3 -m pytest tests/unit -q
py -3 scripts/diagnose_sources.py
py -3 scripts/diagnose_alert_rate.py
py -3 scripts/backtest_thresholds.py
```

