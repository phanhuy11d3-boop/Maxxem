# CryptoSentinel Constitution

This file is the project constitution for Claude, subagents, and human operators.
When it conflicts with older docs, memory files, or historical assumptions, this
file wins.

## Product Truth

CryptoSentinel is being rebuilt into a DEXScreener-style price-move alert system.
The first-class output is direct, numeric coin/pair movement: which pair moved,
by how much, over which horizon, with what volume, liquidity, buy/sell activity,
and a source link.

RSS/news and LLM analysis are secondary context. They must not crowd out direct
pair movement alerts, and they must never invent numbers for a DEX alert.

## Non-Negotiables

1. **DEX-first**: `config/dexscreener.yaml`, `scrapers/dexscreener.py`, and
   `scripts/diagnose_dexscreener.py` are the product core until the refactor
   introduces the new signal engine.
2. **Pinned pairs only in production**: every production watchlist entry must
   include `chainId`, `pairAddress`, `baseSymbol`, and `quoteSymbol`. Search-only
   entries are allowed only during diagnosis.
3. **No silent quiet**: if alerts are low, first prove whether no watched pair
   crossed thresholds or the scanner is broken:
   `py -3 scripts/diagnose_dexscreener.py`.
4. **No hallucinated metrics**: price change, volume, liquidity, txns, and pair
   identity come from market/on-chain APIs, not from an LLM.
5. **Live output is explicit**: commands that can write production DB state or
   send Telegram messages must be described as live-fire and should require an
   explicit flag or human intent.
6. **Stale protection**: trading alerts older than the configured freshness
   window must expire instead of being sent late.
7. **Outbox discipline**: Telegram delivery goes through `tg_status`; do not
   treat `processed=True` alone as proof that a signal was delivered.
8. **Context hygiene**: old memory and archived docs are historical evidence,
   not current source of truth. Do not let old RSS/LLM assumptions steer new
   DEX-first design.
9. **SOP form stays Claude-compatible**: project subagents live in
   `.claude/agents/*.md`; project skills live in
   `.claude/skills/<skill-name>/SKILL.md`; both use YAML frontmatter.
10. **Refactor by strangler migration**: keep the current working bot alive while
    building the new package around it, then retire legacy paths with tests and
    migration notes.

## Source-Of-Truth Order

1. `CLAUDE.md`
2. `docs/refactor-master-plan.md`
3. Current code and tests
4. `docs/architecture.md`, `docs/operations.md`, `docs/guardrails.md`
5. `.claude/agents/*` and `.claude/skills/*`
6. `MEMORY.md` and `.claude/agent-memory/*`

If a lower layer disagrees with a higher layer, update the lower layer or call
out the mismatch. Do not silently follow the older layer.

## Current Runtime Map

| Area | Current file |
|---|---|
| Production entrypoint | `main.py` |
| Experimental agentic runtime | `agentic_runtime.py` |
| DEX price-move scanner | `scrapers/dexscreener.py` |
| DEX watchlist/thresholds | `config/dexscreener.yaml` |
| DEX diagnosis | `scripts/diagnose_dexscreener.py` |
| RSS/news secondary ingest | `scrapers/generic_rss.py`, `config/sources.yaml` |
| Optional fast APIs | `scrapers/fast_signals.py` |
| LLM news analysis | `processors/insight_extractor.py` |
| Data contract | `models/article.py` |
| Storage/outbox | `storage/postgres.py` |
| Telegram delivery | `utils/notifier.py` |

## Safe Commands

| Purpose | Command |
|---|---|
| Unit tests | `py -3 -m pytest tests/unit -q` |
| Compile core files | `py -3 -m py_compile main.py agentic_runtime.py models/article.py storage/postgres.py scrapers/dexscreener.py scrapers/generic_rss.py processors/insight_extractor.py utils/notifier.py` |
| Diagnose DEX scanner | `py -3 scripts/diagnose_dexscreener.py` |
| Dry preflight | `py -3 .claude/skills/preflight/scripts/run_preflight.py` |
| Live production run | `py -3 main.py` |
| Live experimental agentic run | `py -3 main.py --agentic` |

`py -3 main.py`, `py -3 main.py --legacy`, and `py -3 main.py --agentic` can
write DB state and send Telegram. Use them only when a live run is intended.

## Refactor North Star

The target architecture is documented in `docs/refactor-master-plan.md`. The
new repo should converge toward a package-style structure with explicit domains:
market data ingestion, signal engine, storage, delivery, observability, and SOPs.
Legacy `Article`/RSS/LLM code remains only as a compatibility layer until the new
`SignalEvent` and alert pipeline replace it.

## Agent And Skill Policy

- Keep subagent frontmatter short and discoverable: `name`, `description`,
  `tools`, optional `memory`, optional `skills`.
- Keep skill frontmatter short: `name`, `description`, optional safety fields
  such as `disable-model-invocation` and `allowed-tools`.
- Skills should load detailed context only when needed. Prefer small procedures,
  helper scripts, and clear verification commands over long essays.
- Any skill that can touch production DB or Telegram must say so in the first
  screen and require an explicit live flag in its script.

## Business Bar

A change is valuable only if it improves at least one of these:

- faster detection of meaningful pair movement;
- fewer wrong-pair or stale alerts;
- better signal-to-noise for traders;
- easier watchlist/threshold tuning;
- stronger evidence in every alert;
- safer operations with fewer silent failures.

Cosmetic docs, generic crypto-news features, and LLM-only commentary do not pass
the bar unless they support the DEX-first alert product.
