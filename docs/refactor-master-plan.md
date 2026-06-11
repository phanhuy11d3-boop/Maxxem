# CryptoSentinel Refactor Master Plan

This is the plan for turning the current repo from a mixed crypto-news bot into a
focused DEXScreener-style market movement product. It is intentionally broader
than a code TODO list: it covers product scope, business value, repo shape, SOPs,
data contracts, migration order, risks, and kill criteria.

## 0. Current Diagnosis

The repo already has valuable pieces:

- working Python scheduler/runtime with Telegram output;
- Supabase/Postgres storage and Telegram outbox state;
- DEXScreener pair-move scanner and pinned watchlist;
- diagnosis scripts for DEX, LLM, recent processing, Telegram, cadence;
- Claude-style project subagents and skills;
- unit tests around hardening and DEX alerts.

The repo also carries real debt:

- product identity is split between news aggregation, LLM analysis, and direct
  DEX price alerts;
- `Article` is overloaded as both news article and price-move alert;
- docs and SOPs still teach old RSS/LLM-first behavior;
- `main.py` owns too many concerns: scheduling, DB, LLM batching, Telegram, state;
- live smoke tests can touch production DB/Telegram unless guarded;
- historical memory can dilute current context if treated as source of truth;
- there is no clean event model for observations, signal events, alert decisions,
  delivery attempts, and health metrics.

## 1. Product Thesis

CryptoSentinel should become a fast, evidence-rich alerting system for direct
token/pair movement.

Primary user jobs:

1. Know quickly when a watched coin/pair moves meaningfully.
2. See the numerical reason for the alert without opening DEXScreener first.
3. Avoid stale, wrong-pair, low-liquidity, or repeated spam alerts.
4. Tune watchlists and thresholds without breaking the bot.
5. Add on-chain context only when it explains the move.

Not the product:

- generic crypto news feed;
- LLM-written market commentary;
- social-media content mill;
- unsupported trading advice or buy/sell instructions;
- every micro-move from illiquid pairs.

## 2. Feature Set

### V1 Core

- Pinned pair watchlist with per-pair overrides.
- DEXScreener polling by exact `chainId` + `pairAddress`.
- Multi-horizon movement checks: `m5`, `h1`, `h6`, `h24`.
- Minimum liquidity and volume gates.
- Directional alerts: pump, dump, breakout, reversal candidate.
- Cooldown and dedup by pair + horizon + direction + time bucket.
- Telegram alert with pair, price, percent move, horizon, volume, liquidity,
  buy/sell txns, chain, DEX, and source link.
- Read-only diagnosis that explains no-trigger vs broken scanner.
- Dry preflight that never sends Telegram by default.

### V1.5 Signal Quality

- Pair registry with canonical symbols and known-safe pair addresses.
- Dynamic thresholds by volatility/liquidity tier.
- Alert severity score using move %, volume, liquidity, txns imbalance, and
  watchlist priority.
- Alert suppression for suspicious illiquidity or pool manipulation.
- Daily/shift summary: top movers, missed thresholds, quiet-state explanation.
- Source health table: API status, latency, failure count, last good fetch.

### V2 On-Chain Enrichment

- Token holder concentration snapshot where API support exists.
- Large swap / whale transfer enrichment.
- Liquidity add/remove detection.
- CEX/DEX divergence check for major assets.
- Funding/open-interest/liquidation context for BTC/ETH/SOL when available.
- Enrichment must be optional and never block the base price alert.

### V3 Operator Product

- CLI for watchlist add/remove/tune/validate.
- Config validator with wrong-pair and missing-field checks.
- Backtest/replay against saved snapshots.
- Admin dashboard or text report for source health and alert quality.
- Alert templates per channel: main, premium, admin.
- Human review tools for false positive/false negative labeling.

## 3. Target Repo Structure

```text
crypto-sentinel/
├── src/
│   └── cryptosentinel/
│       ├── __init__.py
│       ├── cli.py
│       ├── config/
│       │   ├── loader.py
│       │   ├── schemas.py
│       │   └── validators.py
│       ├── domain/
│       │   ├── pair.py
│       │   ├── observation.py
│       │   ├── signal_event.py
│       │   ├── alert.py
│       │   └── health.py
│       ├── ingest/
│       │   ├── dexscreener.py
│       │   ├── onchain/
│       │   │   ├── base.py
│       │   │   ├── transfers.py
│       │   │   └── liquidity.py
│       │   └── rss_legacy.py
│       ├── signals/
│       │   ├── engine.py
│       │   ├── rules.py
│       │   ├── scoring.py
│       │   └── cooldown.py
│       ├── storage/
│       │   ├── postgres.py
│       │   ├── migrations/
│       │   └── repositories.py
│       ├── delivery/
│       │   ├── telegram.py
│       │   ├── templates.py
│       │   └── outbox.py
│       ├── observability/
│       │   ├── heartbeat.py
│       │   ├── source_health.py
│       │   └── diagnostics.py
│       └── legacy/
│           ├── article_adapter.py
│           └── news_pipeline.py
├── apps/
│   ├── worker.py
│   └── admin_cli.py
├── config/
│   ├── dexscreener.yaml
│   ├── sources.yaml
│   └── alert_templates.yaml
├── scripts/
│   ├── diagnose_dexscreener.py
│   ├── validate_config.py
│   ├── replay_snapshots.py
│   └── migrate_legacy.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── fixtures/
│   └── golden/
├── docs/
│   ├── refactor-master-plan.md
│   ├── architecture.md
│   ├── operations.md
│   ├── guardrails.md
│   └── adr/
├── .claude/
│   ├── agents/
│   ├── skills/
│   └── rules/
├── .github/workflows/
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

## 4. New Data Model

Replace the overloaded `Article` center with explicit domain objects:

- `Pair`: chain, pair address, base/quote, DEX, liquidity tier, status.
- `MarketObservation`: raw snapshot from DEX/API at a point in time.
- `SignalEvent`: rule-triggered movement event with evidence and score.
- `AlertDecision`: whether to send, suppress, cooldown, expire, or escalate.
- `DeliveryAttempt`: Telegram/send state and error history.
- `SourceHealth`: API status, latency, failure windows, last good response.
- `PipelineRun`: per-run counts, errors, and duration.

Suggested tables:

```sql
pairs(id, chain_id, pair_address, base_symbol, quote_symbol, dex_id,
      active, priority, min_liquidity_usd, created_at, updated_at)

market_observations(id, pair_id, observed_at, price_usd, liquidity_usd,
                    volume_m5, volume_h1, volume_h6, volume_h24,
                    change_m5, change_h1, change_h6, change_h24,
                    txns_json, raw_json)

signal_events(id, pair_id, observation_id, horizon, direction, change_pct,
              severity, score, evidence_json, dedup_key, occurred_at,
              expires_at, status)

alert_outbox(id, signal_event_id, channel, status, attempts, last_error,
             next_attempt_at, sent_at, created_at)

source_health(id, source, status, latency_ms, error, checked_at)

pipeline_runs(id, started_at, finished_at, scraped_count, signal_count,
              sent_count, suppressed_count, error_count, metadata_json)
```

Keep `articles` temporarily for RSS/news compatibility, then deprecate it after
the signal path is stable.

## 5. Current File Disposition

| Current path | Decision | Reason |
|---|---|---|
| `scrapers/dexscreener.py` | Keep, then move/rewrite into `src/cryptosentinel/ingest/dexscreener.py` | Good product fit; needs domain model output |
| `config/dexscreener.yaml` | Keep and strengthen validation | Core watchlist |
| `scripts/diagnose_dexscreener.py` | Keep, then move shared logic into observability | Critical no-silent-quiet tool |
| `models/article.py` | Keep as legacy adapter | Too overloaded for new product |
| `storage/postgres.py` | Split | Storage, migrations, repositories, outbox are mixed |
| `main.py` | Replace with thin `apps/worker.py` | Too many responsibilities |
| `agentic_runtime.py` | Archive or rebuild later | Current runtime mirrors old pipeline, not product core |
| `processors/insight_extractor.py` | Keep as legacy news context | Not part of direct DEX alerts |
| `scrapers/generic_rss.py` | Move to `legacy/rss_legacy.py` | Secondary context only |
| `scrapers/fast_signals.py` | Re-evaluate | Keep only sources that explain price movement |
| `utils/notifier.py` | Split into delivery templates/outbox/client | Delivery and formatting need stronger boundaries |
| `characters/sentinel.json` | Quarantine unless a runtime uses it | Context noise from earlier persona/tooling |
| `.claude/agent-memory/*` | Keep but demote | Historical evidence, not source of truth |
| `.claude/agents/*` | Keep form, rewrite scopes | Valuable SOP shell |
| `.claude/skills/*` | Keep form, prune live-risk defaults | Valuable SOP shell |

## 6. Migration Phases

### Phase 0: Freeze And Inventory

- Keep current working bot on `main`.
- Confirm remote is clean and tests pass.
- Mark `CLAUDE.md` and this plan as source of truth.
- Add a deletion/quarantine list before removing old files.

Exit criteria:

- `py -3 -m pytest tests/unit -q` passes.
- `py -3 scripts/diagnose_dexscreener.py` proves scanner health.
- `git status` is understood.

### Phase 1: Context And SOP Cleanup

- Rewrite `CLAUDE.md` to DEX-first constitution.
- Update `.claude/agents/*` so each agent states whether it owns DEX core,
  legacy news, delivery, storage, or ops.
- Update skills:
  - `dexscreener-watchlist`: core watchlist SOP;
  - `preflight`: dry by default, live only with explicit flag;
  - `health-sweep`: DEX diagnosis first;
  - `add-source`: legacy RSS only;
  - add future `signal-rule-tuning` and `config-validation` skills.
- Update `.claude/rules/interaction.md` so subagents cannot imply nonexistent
  runtime behavior.

Exit criteria:

- No SOP says live pipeline is safe by default.
- No SOP frames RSS/news as the primary product.

### Phase 2: Package Skeleton And Config Validation

- Add `pyproject.toml` and `src/cryptosentinel`.
- Implement config schemas for DEX watchlist and alert thresholds.
- Add `scripts/validate_config.py`.
- Add tests for missing `pairAddress`, wrong threshold types, duplicated pairs,
  invalid cooldowns, and unsafe search-only production entries.

Exit criteria:

- Config validation runs in CI.
- Current `config/dexscreener.yaml` passes.

### Phase 3: Domain Model And Storage

- Create domain models: `Pair`, `MarketObservation`, `SignalEvent`,
  `AlertDecision`.
- Add migrations for new tables.
- Write repositories with typed insert/read methods.
- Keep old `Article` path running through an adapter.

Exit criteria:

- Unit tests prove dedup/cooldown semantics.
- Migration can run twice safely.
- Old bot still works.

### Phase 4: DEX Ingestion And Signal Engine

- Convert DEXScreener fetch into `MarketObservation`.
- Build rule engine that emits `SignalEvent`.
- Implement score and severity.
- Implement cooldown/suppression before outbox.
- Save raw API fragments for audit.

Exit criteria:

- Fixture replay emits expected events.
- No wrong-pair alert can pass config validation.
- Quiet state is explainable.

### Phase 5: Delivery Redesign

- Split Telegram client, templates, and outbox state.
- Render DEX alerts from `SignalEvent`, not `Article`.
- Add channel policy: main/premium/admin.
- Ensure retries, expiry, and stale handling are explicit.

Exit criteria:

- Delivery tests cover sent/failed/expired/pending.
- HTML escaping tests cover symbols, URLs, and special characters.
- No live sends in tests.

### Phase 6: Observability And Operator UX

- Create `source_health` tracking.
- Add `pipeline_runs`.
- Add CLI commands:
  - `cs diagnose dex`;
  - `cs validate config`;
  - `cs watchlist add`;
  - `cs watchlist tune`;
  - `cs replay fixtures`.
- Add shift summary and no-trigger report.

Exit criteria:

- Operator can answer: bot quiet because healthy/no trigger, API down, DB down,
  threshold too high, or delivery stuck.

### Phase 7: On-Chain Enrichment

- Add optional enrichment providers behind interfaces.
- Never block DEX alert on enrichment timeout.
- Attach enrichment as evidence fields with source and timestamp.
- Add confidence labels for incomplete enrichment.

Exit criteria:

- Base DEX alert still sends when enrichment fails.
- Enrichment is visible as context, not invented narrative.

### Phase 8: Legacy Retirement

- Move RSS/LLM pipeline under `legacy/`.
- Delete or archive unused persona/config artifacts.
- Update README and architecture to the new package.
- Remove old docs that contradict the constitution.

Exit criteria:

- No production path depends on `Article` for DEX alerts.
- No docs instruct RSS/LLM-first operation.
- CI covers config, signal engine, storage, delivery, and diagnostics.

## 7. SOP And Claude Design

This repo should follow the current Claude Code shape:

- project subagents in `.claude/agents/*.md`;
- project skills in `.claude/skills/<skill-name>/SKILL.md`;
- YAML frontmatter kept concise so Claude can discover the right agent/skill;
- detailed procedures loaded only when needed.

Reference docs checked:

- Claude Code subagents:
  <https://docs.anthropic.com/en/docs/claude-code/sub-agents>
- Claude Code skills:
  <https://docs.anthropic.com/en/docs/claude-code/skills>

Target agents:

- `ingestion-scout`: DEX/API ingestion and watchlist health.
- `signal-engineer`: movement rules, scoring, false positives/negatives.
- `db-auditor`: migrations, dedup, outbox, source health, no silent state drift.
- `notifier-broadcaster`: Telegram templates, channel routing, delivery SLA.
- `ops-manager`: CI, scheduler, dry/live preflight, deployment health.
- `product-reviewer`: market fit, alert quality, user workflows.

Target skills:

- `dexscreener-watchlist`: add/tune/diagnose watched pairs.
- `signal-rule-tuning`: threshold/scoring changes with replay tests.
- `config-validation`: schema and production-safety checks.
- `preflight`: dry default; `--live` required for production pipeline.
- `health-sweep`: DEX first, then DB/outbox, then LLM/news.
- `legacy-news-source`: RSS source maintenance only, never primary product.

## 8. Test Strategy

Unit tests:

- config validation;
- pair canonicalization;
- DEX observation parsing;
- signal rule thresholds;
- cooldown and dedup keys;
- alert template rendering;
- outbox state transitions.

Contract tests:

- DEXScreener response fixtures;
- Telegram API payload shape;
- DB migration idempotency.

Integration tests:

- observation -> signal -> outbox, with fake DB/Telegram;
- diagnosis no-trigger vs API failure;
- replay saved snapshots.

Operational tests:

- dry preflight in CI;
- config validator in CI;
- live preflight only by explicit manual operation;
- source health query after each run.

Golden tests:

- known pump/dump fixtures should alert;
- known low-liquidity moves should suppress;
- wrong-pair fixture should fail validation;
- stale alert should expire.

## 9. Risk Register

| Risk | Impact | Prevention |
|---|---|---|
| Wrong pair selected by search | Severe trust loss | Production requires pinned `chainId` + `pairAddress`; config validator blocks search-only |
| Bot goes quiet silently | Missed signals | Read-only DEX diagnosis; source health table; no-trigger report |
| Alert spam | Channel fatigue | Cooldown, severity score, liquidity/volume gates, per-pair overrides |
| Stale trading alert | Bad user outcome | Expiry window enforced before delivery |
| LLM invents metrics | Trust loss | DEX metrics bypass LLM entirely |
| On-chain API timeout blocks alert | Missed fast move | Enrichment optional and time-boxed |
| DB migration breaks live bot | Downtime | Idempotent migrations, shadow tables, rollback plan, adapter layer |
| Existing RSS code dilutes context | Lower AI output quality | Move to legacy namespace and demote SOPs |
| Live preflight sends unexpectedly | User confusion | Dry default; `--live` flag for production run |
| API rate limit | Gaps | Backoff, source health, cache observations, per-source timeout |
| Telegram formatting break | Dropped messages | Template tests with HTML escaping |
| Secrets leak in docs/tests | Security incident | CI secret grep and placeholder-only docs |
| Thresholds too high/low | Noisy or quiet product | Replay tests and operator tuning reports |
| Agent SOP drift | Future silent bugs | Constitution precedence and periodic SOP audit |

## 10. Business Value And Metrics

Value proposition:

- traders get fast direct movement alerts without reading generic news;
- each alert is evidence-rich enough to decide whether to inspect the chart;
- operator can tune and debug without guessing;
- system can expand into on-chain context without losing the core alert speed.

Core metrics:

- alert latency from observation to Telegram;
- true-positive rate by operator labeling;
- false-positive reasons: illiquid, duplicate, stale, wrong-pair, noise;
- no-trigger periods explained by diagnosis;
- source uptime and API latency;
- delivery success rate;
- alerts per day by severity and pair;
- user retention or channel engagement if available.

Kill criteria:

- if most alerts require LLM commentary to feel useful, the product has drifted;
- if users cannot trust pair identity and numbers, stop feature work and fix data;
- if quiet periods cannot be explained, stop growth work and fix observability;
- if channel output becomes generic news, the refactor failed.

## 11. Immediate Next Actions

1. Finish SOP cleanup: agents, skills, rules, operations docs.
2. Make dry preflight the default and add explicit `--live`.
3. Add config validator for `config/dexscreener.yaml`.
4. Add package skeleton and domain models without replacing current runtime yet.
5. Add migration plan for `pairs`, `market_observations`, `signal_events`,
   `alert_outbox`, `source_health`, and `pipeline_runs`.
6. Build the new DEX signal path in parallel with current `Article` path.
7. Cut over Telegram templates from `Article` to `SignalEvent`.
8. Archive legacy RSS/LLM docs after the DEX path is stable.
