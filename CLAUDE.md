# CryptoSentinel Constitution

This file is the project constitution for Claude, subagents, and human operators.
When it conflicts with older docs, memory files, or historical assumptions, this
file wins.

## Product Truth

CryptoSentinel IS a DEXScreener-style price-move alert system. The only output
is direct, numeric coin/pair movement: which pair moved, by how much, over
which horizon, with what volume, liquidity, buy/sell activity, and a chart link.

There is NO news. NO RSS. NO LLM. NO sentiment. NO bullish/bearish labels.
The direction of a move is the sign of `change_pct` — a fact, not an opinion.
The big-bang removal of the legacy news pipeline was executed 2026-06-12; the
old `articles` table remains in the DB as frozen history only.

## Non-Negotiables

1. **DEX-only**: `config/dexscreener.yaml`, `scrapers/dexscreener.py`,
   `models/pair_signal.py`, `storage/postgres.py`, `utils/notifier.py`, `main.py`
   are the whole product. Do not reintroduce news/LLM paths.
2. **Pinned pairs only in production**: every production watchlist entry must
   include `chainId`, `pairAddress`, `baseSymbol`, and `quoteSymbol`. Search
   resolution is allowed only in diagnosis/discovery.
3. **No silent quiet**: if alerts are low, invoke the `/health-sweep` skill —
   it fans out scanner, rules, DB, and delivery in parallel and cross-correlates
   all stages. Do not run a single diagnostic script in place of the skill.
   Quiet with a healthy scanner is a valid, healthy state.
4. **No hallucinated metrics**: every number in an alert comes from the
   DEXScreener API response. Nothing is estimated, labeled, or narrated.
5. **Live output is explicit**: `py -3 main.py`, `py -3 utils/notifier.py
   --live`, and preflight `--live` write production DB state and/or send
   Telegram. Name them as live-fire before running.
6. **Stale protection**: alerts older than 30 minutes expire
   (`expire_stale_tg_queue`) instead of being sent late. A late price alert is
   a wrong price alert.
7. **Outbox discipline**: delivery state lives in `signals.tg_status`
   (pending → sent | failed → expired) with `claim_tg_send_slot` lease
   serializing the two production shifts. Never bypass the claim.
8. **Context hygiene**: old memory, archived docs, and git history about the
   news/LLM era are historical evidence, not current truth. Do not let them
   steer design.
9. **SOP form stays Claude-compatible**: project subagents live in
   `.claude/agents/*.md`; project skills in `.claude/skills/<name>/SKILL.md`;
   both use YAML frontmatter.
10. **Schema changes are additive**: `init_db()` stays idempotent; no
    destructive statements on live tables without explicit operator request.

## Source-Of-Truth Order

1. `CLAUDE.md`
2. Current code and tests
3. `docs/architecture.md`, `docs/operations.md`, `docs/guardrails.md`
4. `docs/refactor-master-plan.md` (executed plan + risk register)
5. `.claude/agents/*` and `.claude/skills/*`
6. `MEMORY.md` and `.claude/agent-memory/*`

If a lower layer disagrees with a higher layer, update the lower layer or call
out the mismatch. Do not silently follow the older layer.

## Runtime Map

| Area | File |
|---|---|
| Orchestrator (1 vòng pipeline) | `main.py` |
| Data contract + Telegram render | `models/pair_signal.py` (`PairSignal`) |
| Conviction layer (score + chain) | `models/scoring.py` (deterministic, no LLM) |
| DEX scanner (batch fetch + rules) | `scrapers/dexscreener.py` |
| Watchlist/thresholds/scoring weights | `config/dexscreener.yaml` |
| Storage + outbox | `storage/postgres.py` (bảng `signals`) |
| Telegram delivery + heartbeat + digest render | `utils/notifier.py` |
| Scanner diagnosis (read-only) | `scripts/diagnose_dexscreener.py` |
| Outbox diagnosis (read-only) | `scripts/diagnose_outbox.py` |
| Score diagnosis (read-only) | `scripts/diagnose_scores.py` |
| Daily top-movers digest (live-fire send) | `scripts/daily_digest.py` |
| Day shift scheduler | `scripts/run_local_pipeline.ps1` + `.vbs` (Task Scheduler) |
| Night shift scheduler | `.github/workflows/scraper.yml` (GH Actions shift loop) |

## Safe Commands

| Purpose | Command |
|---|---|
| Unit tests | `py -3 -m pytest tests/unit -q` |
| Compile core files | `py -3 -m py_compile main.py models/pair_signal.py models/scoring.py storage/postgres.py scrapers/dexscreener.py utils/notifier.py` |
| Diagnose DEX scanner | `py -3 scripts/diagnose_dexscreener.py` |
| Diagnose outbox | `py -3 scripts/diagnose_outbox.py` |
| Diagnose conviction scores | `py -3 scripts/diagnose_scores.py` |
| Preview daily digest (dry) | `py -3 scripts/daily_digest.py` |
| Dry preflight | `py -3 .claude/skills/preflight/scripts/run_preflight.py` |
| Live production run | `py -3 main.py` (LIVE-FIRE) |

## Telegram Format Contract

Every alert renders from `PairSignal.format_telegram_html()` — layout copied
from the market's most engaging price-alert channels (Whale Alert magnitude
emojis, buy-bot pressure bars, cashtags, action links, hashtags):

- line 1 hook: 🚀/🩸 lặp 1-5 lần theo |%| + `$CASHTAG` + % + horizon + ⚡ khi hot;
- buy-pressure bar 🟢🔴 (8 ô, kèm % và buys/sells thô; ẩn khi < 10 txns);
- price — pair · DEX · chain;
- multi-horizon row (5m/1h/6h/24h);
- conviction row `🎯 <score>/100 · <transmission chain>` — điểm tin cậy
  deterministic 0–100 + chuỗi bằng chứng trung tính (vd `vol 3.2× gate · 71%
  buys · m5+h1 aligned`); ẩn khi score = None (row cũ / scoring tắt);
- volume · liquidity · market cap;
- `⚠️ Low liquidity — DYOR` khi liquidity < $100k;
- action row: 📈 Chart | 🔁 Swap (jup.ag cho Solana, Uniswap cho Ethereum);
- hashtags `#TOKEN #Chain` + giờ ICT.

Conviction score (`models/scoring.py`) là SỐ HỌC deterministic, không LLM,
không opinion — `transmission_chain` chỉ dùng từ vựng trung tính, chịu test
từ-cấm. Score CHỈ để hiển thị + lưu + augment routing premium; theo doctrine
"thà noise còn hơn miss" nó KHÔNG BAO GIỜ chặn kênh chính.

No sentiment line, no urgency labels, no AI disclaimer, no news layout. Tests
in `tests/unit/test_signal_format.py` + `test_scoring.py` enforce zero banned words.

## Agent And Skill Policy

- Keep subagent frontmatter short and discoverable: `name`, `description`,
  `tools`, optional `memory`, optional `skills`, optional read-only hooks.
- Read-only agents (db-auditor, notifier-broadcaster) are guarded by
  `scripts/hooks/guard_readonly.py --block sqlwrite livefire`.
- Skills load detailed context only when needed. Any skill that can touch
  production DB or Telegram must say so on the first screen and require an
  explicit live flag.

## Business Bar

A change is valuable only if it improves at least one of these:

- faster detection of meaningful pair movement;
- fewer wrong-pair or stale alerts;
- better signal-to-noise for traders;
- easier watchlist/threshold tuning;
- stronger evidence in every alert;
- safer operations with fewer silent failures.

Generic crypto-news features and LLM commentary are out of scope permanently.

## Source Adapter Addendum

The scanner now has an explicit source layer:

- `sources/base.py` defines `PairSnapshot` and `SourceHealth`.
- `sources/dexscreener_rest.py` is the production DEXScreener REST adapter.
- `sources/normalize.py` converts provider payloads into normalized snapshots.
- `signals/engine.py` evaluates deterministic trigger rules and builds `PairSignal`.
- `scrapers/dexscreener.py` remains the compatibility facade for diagnostics and `main.py`.

Source health is production telemetry, not a trading signal. Healthy source plus
no trigger is healthy quiet. Degraded or unhealthy source plus no trigger means
quiet is not trustworthy.

New read-only diagnostics:

- `py -3 scripts/diagnose_sources.py`
- `py -3 scripts/diagnose_alert_rate.py`
- `py -3 scripts/backtest_thresholds.py`

Realtime sources must start as shadow/canary: no production `signals` writes,
no Telegram sends, no promotion without explicit operator approval.
