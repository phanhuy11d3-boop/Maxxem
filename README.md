# CryptoSentinel

Theo dõi biến động giá coin/pair trực tiếp kiểu DEXScreener → bổ sung tin crypto nhanh → phân phối Telegram **trading-grade**: cadence 1 phút, stale 30 phút, outbox Telegram, recall-first (nhãn `[?]` low confidence thay vì im lặng).

## Stack

| Thành phần | Công nghệ |
|---|---|
| Runtime | Python 3.11+ |
| LLM | Gateway OpenAI-compatible (`LLM_BASE_URL` + `LLM_MODEL`, tùy chọn `LLM_MODEL_FAST`/`LLM_MODEL_POWER`) |
| DB | Supabase / PostgreSQL (`storage/postgres.py`, connection pool) |
| Scheduler | Hai ca: **Task Scheduler local** (ngày, cadence 1 phút) + **GH Actions shift loop** (đêm, mỗi run là ca ~5h30 tự loop mỗi phút — GH không tôn trọng cron mỗi-phút) |
| Output | Telegram Bot API |
| Ingest | `scrapers/dexscreener.py` (DEX pair moves) + `feedparser` (RSS) + `scrapers/fast_signals.py` (API tùy chọn) |

## Luồng tóm tắt

```text
Shift (local 1m / GH loop) → main.py
  → expire + dispatch TG backlog
  → scrape (DEXScreener pair moves + RSS + optional fast APIs)
  → upsert / dedup Postgres
  → LLM (tiered: Tier-1 skip triage; Tier-2 triage)
  → mark_processed_with_tg → dispatch TG queue
  → heartbeat (chỉ khi ENABLE_OPS_TELEMETRY bật)
```

## Cấu trúc thư mục (lõi)

```text
crypto-sentinel/
├── main.py
├── agentic_runtime.py          # --agentic, fallback legacy
├── models/article.py
├── scrapers/generic_rss.py
├── scrapers/dexscreener.py
├── scrapers/fast_signals.py
├── processors/insight_extractor.py
├── storage/postgres.py
├── utils/notifier.py
├── config/sources.yaml
├── config/dexscreener.yaml
├── docs/
│   ├── architecture.md         # Kiến trúc + schema + outbox (SSOT kỹ thuật)
│   ├── guardrails.md
│   └── operations.md           # QA, smoke test, biến env
├── .github/workflows/scraper.yml
├── tests/unit/
├── requirements.txt
├── .env.example
├── CLAUDE.md                   # Lệnh nhanh cho AI/agent playbook
└── MEMORY.md
```

## Biến môi trường

Xem **`.env.example`**. Tóm tắt:

| Biến | Mô tả |
|---|---|
| `DATABASE_URL` | URI PostgreSQL Supabase |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | LLM gateway OpenAI-compatible (URL phải public khi chạy trên Actions) |
| `BOT_TOKEN` | Telegram bot |
| `CHAT_ID` | Kênh/ group **signal** |
| `PREMIUM_CHAT_ID` | Tùy chọn |
| `UW_API_KEY`, `ARKHAM_API_KEY` | Tùy chọn (fast signals) |
| `ADMIN_CHAT_ID`, `HEARTBEAT_CHAT_ID` | Ops alerts / heartbeat (telemetry) |
| `ENABLE_OPS_TELEMETRY` | `0` tắt, `1`/true bật heartbeat + admin alert |

## CLI

- **`py -3 main.py`** — Windows (Python Launcher).
- **`python main.py`** — macOS/Linux/CI.
- **`py -3 main.py --legacy`** — tương đương mặc định.
- **`py -3 main.py --agentic`** — runtime agentic có fallback legacy.
- **`py -3 -m pytest tests/unit`** — unit tests.

Audit tĩnh DB (nếu có): `py -3 scripts/audit_agent.py`.
Diagnose DEX price-move scanner: `py -3 scripts/diagnose_dexscreener.py`.

## Tài liệu

- [`docs/architecture.md`](docs/architecture.md) — pipeline, DB, LLM, tiers, file map.
- [`docs/guardrails.md`](docs/guardrails.md) — guardrails nội dung & sản phẩm.
- [`docs/operations.md`](docs/operations.md) — checklist vận hành & smoke test.
- **`MEMORY.md`** — bài học lịch sử (AI).
