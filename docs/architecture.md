# Architecture — CryptoSentinel (trading-grade pipeline)

> Pipeline mặc định: **legacy linear** trong `main.py`. Chế độ `python main.py --agentic` dùng `agentic_runtime.py` (cùng storage + Groq), có fallback về legacy nếu lỗi nặng.

Tài liệu này thay cho `implementation_plan.md` (đã gỡ): mô tả **trạng thái hiện tại** của code và DB.

---

## 1. SLA & nguyên tắc sản phẩm

| Nguyên tắc | Cách enforce |
|---|---|
| Cadence **1 phút** | GitHub Actions `cron: '* * * * *'` trong `.github/workflows/scraper.yml` |
| SLA gửi tin | `utils/notifier.py`: lag (published/scrape → Sent) có thể cảnh báo khi **> 120s** (`SLA_SECONDS`) |
| **Anti-stale 30 phút** | Tin quá cửa sổ **không** vào AI queue (`get_unprocessed`) và outbox actionable bị **`expired`** (`expire_stale_tg_queue`) |
| Recall-first | Tier-1 + fast sources **không** bị triage 8B chặn; Tier-2 triage sai → vẫn vào 70B với **`low_confidence`**; LLM “quên” ID → `processed` + **`low_confidence`** (không tăng `retry_count`) |
| Telegram format | ICT time, Sent, Lag, nhãn `[?]` → `models/article.py::format_telegram_html` |
| Ops không nhiễu kênh chính | Heartbeat/admin **không** gửi tới `CHAT_ID`; bật/tắt bằng `ENABLE_OPS_TELEMETRY` |

---

## 2. Sơ đồ luồng (legacy)

```text
GitHub Actions (mỗi 1 phút)
  └─► main.py::run_legacy_pipeline()
        │
        ├─► expire_stale_tg_queue + get_tg_dispatch_queue
        │     → send_telegram + mark_tg_attempt      (drain backlog trước)
        │
        ├─► scrape_all_feeds()
        │     ├─ config/sources.yaml  (RSS, tier trong comment / thứ tự scrape)
        │     └─ scrapers/fast_signals.py  (optional API: Lookonchain, UW, Arkham — cần key)
        │
        ├─► upsert_article  (Dedup SHA-256 URL đã sanitize)
        │
        ├─► get_unprocessed()
        │     • processed = FALSE, retry_count < 3
        │     • COALESCE(published_at, scraped_at) trong 30 phút
        │     SORT: Tier-1 sources trước, sau đó scraped_at giảm dần
        │
        └─► _process_chunk (mỗi MAX_BATCH_SIZE=20)
              • Tier-1/fast: vào batch 70B trực tiếp
              • Tier-2: triage_articles(client) → Dict[article.id, high_impact]
              • analyze_articles_batch → BatchOutcome OK | TRANSIENT_FAIL | STRUCTURAL_FAIL
              • mark_processed_with_tg(...)  actionable → tg_status='pending', tg_attempts=0
              • _dispatch_tg_queue lần hai (đẩy item vừa enqueue)

finally: send_heartbeat + get_outbox_kpis (chỉ khi ENABLE_OPS_TELEMETRY=bật)
```

---

## 3. Modules & dependency map

```text
main.py
  ├── scrapers/generic_rss.py ──► models/article.py
  ├── scrapers/fast_signals.py ─► models/article.py
  ├── storage/postgres.py ─────► models/article.py
  ├── processors/insight_extractor.py ─► models/article.py (+ Groq)
  └── utils/notifier.py ───────► models/article.py (+ Telegram HTTP)
```

- **Data contract duy nhất:** `models/article.py` (`Article`, `MarketImpact`, `normalize_market_impact`).

Tier constants (mirror trong `agentic_runtime.py`):

```text
FAST_SIGNAL_SOURCES = {"Watcher.Guru", "Lookonchain", "UnusualWhales", "Arkham Alerts"}
TIER1_SOURCES = { Blockworks, CoinDesk, Cointelegraph, Unchained Crypto } ∪ FAST_SIGNAL_SOURCES
```

*(Tên source phải khớp chuỗi `Article.source` từ scraper.)*

---

## 4. Database (Supabase PostgreSQL)

- Backend duy nhất: `storage/postgres.py` + `psycopg2.pool.SimpleConnectionPool`.
- Dedup: `INSERT ... ON CONFLICT (id) DO NOTHING`.

### Bảng `articles` (runtime)

```sql
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    published_from_source BOOLEAN DEFAULT TRUE,
    summary TEXT,
    sentiment REAL,
    market_impact TEXT,
    key_takeaway TEXT,
    narrative_tag TEXT,
    affected_tokens TEXT[],
    urgency TEXT,
    low_confidence BOOLEAN DEFAULT FALSE,
    tg_sent BOOLEAN DEFAULT NULL,
    tg_status TEXT DEFAULT NULL,
    tg_attempts INTEGER DEFAULT 0,
    tg_last_error TEXT,
    tg_last_attempt_at TIMESTAMPTZ,
    tg_sent_at TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    retry_count INTEGER DEFAULT 0
);
```

`init_db()` chạy các `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` để migrate DB cũ.

### Telegram outbox / state machine

- **Actionable** = `processed=TRUE` và `market_impact IN ('bullish','bearish')`.
- **`tg_sent` / `tg_status`:**
  - Neutral: `tg_sent=NULL`, `tg_status=NULL` sau `mark_processed_with_tg`.
  - Actionable mới phân tích: `tg_status='pending'`, `tg_attempts=0`, `tg_sent=NULL` đến khi gửi.
  - **`mark_tg_attempt`**: thành công → `sent` + `tg_sent=TRUE`; thất bại → `failed` + `tg_sent=FALSE`, tăng `tg_attempts`.
  - **`expired`**: actionable quá cửa sổ thời gian (policy 30 phút từ `published_at`/`scraped_at`) → không gửi, không DLQ retry vô hạn.

- **`mark_processed_with_tg`**: một `UPDATE` ghi insight LLM **và** trạng thái enqueue ban đầu → tránh race “processed=TRUE nhưng chưa có hàng chờ Telegram”.

### KPI vận hành

`get_outbox_kpis()`: `pending_count`, `failed_count`, `expired_count_60m`, `oldest_pending_age_min` — heartbeat đọc khi telemetry bật.

---

## 5. Groq / LLM

| Bước | Model | Hành vi |
|---|---|---|
| Triage | `llama-3.1-8b-instant` | Chỉ **Tier-2**. Input JSON `[{idx, title}]`. Output `results` có `idx` + `high_impact`. Parser build **`Dict[str, bool]`** theo **`Article.id`**. Anti-miss: exception hoặc thiếu quá ngưỡng → coi mọi bài high-impact |
| Analyze | `llama-3.3-70b-versatile` | Batch JSON, `response_format=json_object`. Thiếu ID trong batch → đánh neutral + `low_confidence` + processed (Vector 3b) |

`BatchOutcome`: **TRANSIENT_FAIL** (rate limit/network) → `increment_retry` cả chunk; **STRUCTURAL_FAIL** (JSON/schema) → không bump retry + admin alert.

---

## 6. GitHub Actions

File: `.github/workflows/scraper.yml`

- `cron: '* * * * *'`
- `concurrency: cryptosentinel-scraper`, `cancel-in-progress: false`
- Secrets / env tiêu biểu: `DATABASE_URL`, `GROQ_API_KEY`, `BOT_TOKEN`, `CHAT_ID`, optional `UW_API_KEY`, `ARKHAM_API_KEY`, `PREMIUM_CHAT_ID`, `ADMIN_CHAT_ID`, `HEARTBEAT_CHAT_ID`, `ENABLE_OPS_TELEMETRY`.

---

## 7. Inventory file lõi

| Path | Vai trò |
|---|---|
| `main.py` | Orchestrator legacy + CLI |
| `agentic_runtime.py` | Scout/Analyst/… đọc/ghi tương đương, opt-in |
| `models/article.py` | Contract + format Telegram HTML |
| `storage/postgres.py` | Pool, schema, dedup, outbox |
| `scrapers/generic_rss.py` | RSS + gọi `fetch_fast_signals()` |
| `scrapers/fast_signals.py` | Fast API sources (optional keys) |
| `processors/insight_extractor.py` | Groq triage + batch + error class |
| `utils/notifier.py` | Telegram, SLA check, telemetry guards |
| `config/sources.yaml` | Danh sách RSS (tier bằng section comment) |
| `.github/workflows/scraper.yml` | Scheduler |

---

## 8. Tài liệu liên quan

- **`docs/guardrails.md`** — Luật nội dung & prompt alignment.
- **`docs/operations.md`** — Smoke test, review checklist, outbox SLA.
- **`CLAUDE.md`** — Lệnh vận hành ngắn cho AI playbook.
