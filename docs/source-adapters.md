# Source Adapters

CryptoSentinel now treats market data as a source layer:

```text
source adapter -> PairSnapshot -> trigger engine -> PairSignal -> outbox
```

## Contracts

- `sources/base.py`
  - `PairSnapshot`: normalized pair metrics.
  - `SourceHealth`: source/chain freshness and error state.
  - `SourceAdapter`: adapter protocol.
- `sources/dexscreener_rest.py`
  - production adapter for pinned DEXScreener pairs.
- `signals/engine.py`
  - deterministic trigger evaluation from snapshots.

## Modes

- `primary`: can produce production alerts.
- `shadow`: may collect health/samples only; must not insert `signals` or send Telegram.
- `canary`: limited promotion candidate; still requires explicit operator approval.

Realtime feeds must start as `shadow`.

## Health Semantics

- `healthy`: source fetched data successfully.
- `degraded`: partial failure; quiet is not fully trustworthy.
- `unhealthy`: no usable data for the source/chain.

Healthy source + no trigger means healthy quiet. Degraded/unhealthy source + no
trigger means the system cannot trust quiet.

## Diagnostics

```powershell
py -3 scripts/diagnose_sources.py
py -3 scripts/diagnose_dexscreener.py
```

