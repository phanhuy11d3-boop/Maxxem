# CryptoSentinel

Bot cảnh báo **biến động giá coin/pair trực tiếp** kiểu DEXScreener → Telegram.

Một alert = một move thật của một pair thật: `+12.4% (1h)`, giá, volume,
liquidity, buys/sells, link chart. **Không news. Không LLM. Không nhãn
bullish/bearish** — hướng đi của giá là con số, trader tự đọc trong 2 giây.

```text
🚀 WIF/SOL +12.4% · 1h
💰 $2.345 · Raydium · Solana
⏳ 5m +1.1% | 1h +12.4% | 6h +8.0% | 24h +15.3%
📊 Vol 1h $850.0K · 💧 Liq $2.4M
🟢 221 buys · 🔴 109 sells
🧢 MC $2.2B

📈 Chart — DEXScreener
⏱ 23:04 ICT
```

Trading-grade: cadence 1 phút, alert quá 30 phút tự expire (không bao giờ gửi
giá nguội), outbox chống gửi trùng giữa 2 ca production.

## Stack

| Thành phần | Công nghệ |
|---|---|
| Runtime | Python 3.11+ |
| Nguồn dữ liệu | DEXScreener public API (`scrapers/dexscreener.py`, batch theo chain) |
| DB | Supabase / PostgreSQL (`storage/postgres.py`, bảng `signals` + outbox) |
| Scheduler | Hai ca: **Task Scheduler local** (ngày, cadence 1 phút) + **GH Actions shift loop** (đêm, mỗi run là ca ~5h30 tự loop mỗi phút) |
| Output | Telegram Bot API (HTML price-board) |

## Luồng

```text
Shift (local 1m / GH loop) → main.py
  → expire stale + dispatch TG backlog
  → scan DEXScreener watchlist (batch, pinned pairs)
  → PairSignal vượt ngưỡng → insert (dedup cooldown bucket)
  → dispatch TG queue (claim chống trùng 2 ca)
  → heartbeat (chỉ khi ENABLE_OPS_TELEMETRY bật)
```

## Cấu trúc thư mục

```text
crypto-sentinel/
├── main.py                     # orchestrator DEX-only
├── models/signal.py            # PairSignal — data contract + Telegram render
├── scrapers/dexscreener.py     # scanner: batch fetch + trigger rules
├── storage/postgres.py         # bảng signals + outbox state machine
├── utils/notifier.py           # Telegram delivery + heartbeat
├── config/dexscreener.yaml     # watchlist + thresholds (SSOT cấu hình)
├── scripts/
│   ├── diagnose_dexscreener.py # read-only: trigger/no-trigger từng pair
│   ├── diagnose_outbox.py      # read-only: outbox + KPI delivery
│   └── run_local_pipeline.*    # ca ngày Task Scheduler
├── docs/                       # architecture, operations, guardrails, plan
├── .github/workflows/scraper.yml
├── tests/unit/
├── .claude/                    # agents + skills + rules (SOP cho AI)
└── CLAUDE.md                   # hiến pháp dự án
```

## Biến môi trường

Xem **`.env.example`**:

| Biến | Mô tả |
|---|---|
| `DATABASE_URL` | URI PostgreSQL Supabase |
| `BOT_TOKEN` | Telegram bot |
| `CHAT_ID` | Kênh signal chính |
| `PREMIUM_CHAT_ID` | Tùy chọn — chỉ nhận move nóng (m5 ≥8% / bất kỳ khung ≥15%) |
| `ADMIN_CHAT_ID`, `HEARTBEAT_CHAT_ID` | Ops alerts / heartbeat |
| `ENABLE_OPS_TELEMETRY` | `0` tắt, `1` bật heartbeat + admin alert |

## CLI

- **`py -3 main.py`** — chạy 1 vòng pipeline (LIVE: ghi DB + gửi Telegram).
- **`py -3 -m pytest tests/unit -q`** — unit tests.
- **`py -3 scripts/diagnose_dexscreener.py`** — chẩn đoán scanner (read-only).
- **`py -3 scripts/diagnose_outbox.py`** — chẩn đoán delivery (read-only).
- **`py -3 .claude/skills/preflight/scripts/run_preflight.py`** — smoke trước commit (dry).

## Watchlist

Thêm/bớt pair: sửa `config/dexscreener.yaml`. Mỗi entry production phải pin đủ
`chainId` + `pairAddress` + `baseSymbol` + `quoteSymbol` (chống nhầm token).
Quy trình đầy đủ: skill `add-source` / `dexscreener-watchlist` trong `.claude/skills/`.

## Tài liệu

- [`docs/refactor-master-plan.md`](docs/refactor-master-plan.md) — kế hoạch + risk register của cuộc đại phẫu DEX-only (đã thực thi 2026-06-12).
- [`docs/architecture.md`](docs/architecture.md) — pipeline, schema, outbox.
- [`docs/guardrails.md`](docs/guardrails.md) — guardrails sản phẩm.
- [`docs/operations.md`](docs/operations.md) — checklist vận hành & smoke test.
