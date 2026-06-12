# Architecture — CryptoSentinel v3 (DEX-only)

> Một pipeline tuyến tính duy nhất trong `main.py`. Không còn chế độ
> `--legacy`/`--agentic`, không còn RSS/LLM. Tài liệu này mô tả trạng thái
> hiện tại của code và DB; mâu thuẫn thì `CLAUDE.md` thắng.

---

## 1. SLA & nguyên tắc sản phẩm

| Nguyên tắc | Cách enforce |
|---|---|
| Cadence **1 phút** | Hai ca: Task Scheduler local (ngày) + GH Actions shift loop (đêm) |
| SLA gửi alert | `utils/notifier.py`: lag (observed_at → sent) cảnh báo khi **> 120s** (`SLA_SECONDS`) |
| **Anti-stale 30 phút** | `expire_stale_tg_queue`: signal quá cửa sổ bị **`expired`**, không bao giờ gửi muộn |
| Chống gửi trùng 2 ca | `claim_tg_send_slot`: row-lock + lease 180s, kẻ thắng gửi, kẻ thua bỏ qua |
| Chống spam cùng move | `dedup_key = dex:{chain}:{pair}:{horizon}:{direction}:{bucket}` — cooldown bucket nằm ngay trong PK |
| Chống nhầm token | Watchlist pin `pairAddress` + symbol match guard trong scanner |
| Ops không nhiễu kênh chính | Heartbeat/admin **không** gửi tới `CHAT_ID`; gate bằng `ENABLE_OPS_TELEMETRY` |

---

## 2. Sơ đồ luồng

```text
Shift tick (1 phút)
  └─► main.py::run_pipeline()
        │
        ├─► init_db()                            (idempotent)
        ├─► expire_stale_tg_queue (30m)
        ├─► dispatch outbox backlog              (claim → send → mark)
        │
        ├─► scan_watchlist()
        │     ├─ fetch_pairs_batch: gom pairAddress theo chain,
        │     │    GET /latest/dex/pairs/{chain}/{a1,a2,...}  (≤30/req)
        │     ├─ symbol match guard từng entry
        │     ├─ _trigger: liquidity gate → per-horizon threshold + volume gate
        │     │    → khung mạnh nhất thắng
        │     └─ build_signal → PairSignal (đầy đủ số liệu cấu trúc)
        │
        ├─► insert_signals_batch                 (ON CONFLICT id DO NOTHING
        │                                         = cooldown dedup tại cổng DB,
        │                                         row mới vào tg_status='pending')
        ├─► dispatch outbox                      (signal vừa enqueue)
        └─► finally: heartbeat + state.json
```

---

## 3. Data contract — `PairSignal` (`models/signal.py`)

| Nhóm | Field |
|---|---|
| Định danh | `chain_id`, `dex_id`, `pair_address`, `base_symbol`, `quote_symbol`, `url` |
| Trigger | `horizon` (m5/h1/h6/h24), `change_pct` (dấu = hướng) |
| Bằng chứng | `price_usd`, `volume_usd`, `liquidity_usd`, `buys`, `sells`, `changes{...}`, `fdv`, `market_cap` |
| Meta | `observed_at` (UTC), `dedup_key`, `low_liquidity` |
| Computed | `id = sha256(dedup_key)`, `pair_label`, `direction`, `is_hot` |

`format_telegram_html()` render thẳng từ field cấu trúc — không parse text,
không regex, không LLM.

---

## 4. DB schema — bảng `signals` (`storage/postgres.py`)

```sql
signals(
  id TEXT PRIMARY KEY,            -- sha256(dedup_key)
  dedup_key TEXT NOT NULL,
  chain_id, dex_id, pair_address, base_symbol, quote_symbol, url,
  horizon TEXT, change_pct DOUBLE PRECISION,
  price_usd, volume_usd, liquidity_usd DOUBLE PRECISION,
  buys, sells INTEGER,
  change_m5, change_h1, change_h6, change_h24 DOUBLE PRECISION,
  fdv, market_cap DOUBLE PRECISION,
  low_liquidity BOOLEAN,
  observed_at TIMESTAMPTZ, created_at TIMESTAMPTZ,
  -- outbox state machine --
  tg_status TEXT DEFAULT 'pending',   -- pending|sent|failed|expired
  tg_attempts INTEGER,
  tg_last_error TEXT,
  tg_last_attempt_at TIMESTAMPTZ,
  tg_sent_at TIMESTAMPTZ
)
-- index: idx_signals_outbox (tg_status, observed_at)
```

Outbox transitions:

```text
pending ──claim+send OK──► sent
   │  └──send fail──► failed ──retry (≤3, trong 30')──► sent/failed
   └──quá 30 phút──► expired (tg_last_error='stale_expired')
```

Bảng `articles` cũ (news era) vẫn nằm trong DB nhưng **không** được code
đọc/ghi — lịch sử đóng băng.

---

## 5. Hai ca production

| Ca | Cơ chế | Ghi chú |
|---|---|---|
| Ngày | Windows Task Scheduler → `scripts/run_local_pipeline.vbs/.ps1`, tick 1 phút | log `storage/local_cron.log`, tự xoay 5MB |
| Đêm | GH Actions `scraper.yml`: 1 run = ca ~5h30 tự loop mỗi phút; hết ca tự dispatch ca kế (cần `WORKFLOW_PAT`) | run `in_progress` nhiều giờ là HEALTHY |

Hai ca chung Supabase: dedup theo `id`, gửi trùng bị chặn bởi claim lease.
Phân tích coverage: skill `cadence-check`.

---

## 6. Env

Bắt buộc: `DATABASE_URL`, `BOT_TOKEN`, `CHAT_ID`.
Tùy chọn: `PREMIUM_CHAT_ID` (move nóng), `ADMIN_CHAT_ID`, `HEARTBEAT_CHAT_ID`,
`ENABLE_OPS_TELEMETRY`. Không tồn tại biến LLM nào.
