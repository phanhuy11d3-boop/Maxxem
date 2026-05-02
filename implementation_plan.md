# CryptoSentinel — Implementation Plan (v2)

> **Phiên bản:** 2.0 — Python Pipeline
> **Stack:** Python 3.11 · Groq API (Llama 3) · Supabase (PostgreSQL) · GitHub Actions · Telegram
> **Triết lý:** Học bằng cách build. Ưu tiên: miễn phí, đơn giản, có thể debug được.
> **Không dùng:** ElizaOS, n8n, MCP, blockchain RPC, on-chain API trả phí.

---

## Kiến trúc Tổng quan

```
GitHub Actions (cron: mỗi 1h)
        │
        ▼
     main.py  ◄── config/sources.yaml
        │
        ├─► scrapers/generic_rss.py   [Lấy tin từ RSS]
        │         │
        │         ▼
        │   models/article.py         [Validate + Dedup ID]
        │         │
        │         ▼
        ├─► storage/sqlite.py         [Lưu DB, check trùng]
        │         │ (chỉ tin mới)
        │         ▼
        ├─► processors/insight_extractor.py  [Groq LLM phân tích]
        │         │
        │         ▼
        ├─► storage/sqlite.py         [Cập nhật insight vào DB]
        │         │ (chỉ bullish/bearish)
        │         ▼
        └─► utils/notifier.py         [Gửi Telegram]

Database: Supabase PostgreSQL (hosted, free tier, không cần persist qua Artifacts)
```

---

## Phase 1 — Data Contract (models/article.py)

**Mục tiêu:** Chốt chặn dữ liệu bẩn. Không có file này, pipeline không được chạy.

**Trường bắt buộc:**
- `id: str` — SHA-256 hash của URL (computed_field, tự tính)
- `title: str` — min 5 ký tự
- `url: HttpUrl` — validated URL
- `published_at: datetime` — phải có timezone (auto-force UTC nếu thiếu)
- `source: str` — tên nguồn (The Block, CoinDesk...)

**Trường Optional (LLM điền sau):**
- `summary: Optional[str]` — RSS description, có thể rỗng
- `sentiment: Optional[float]` — -1.0 đến +1.0
- `market_impact: Optional[MarketImpact]` — Enum: bullish/bearish/neutral
- `key_takeaway: Optional[str]` — 1 câu tóm tắt cốt lõi

**Quy tắc `MarketImpact`:**
```python
# LLM trả về bất kỳ string gì → normalize về Enum
# "Bullish", "BULLISH", "bullish trend" → MarketImpact.BULLISH
# Không match → MarketImpact.NEUTRAL (không throw error)
```

**Trường hệ thống:**
- `scraped_at: datetime` — thời điểm cào (auto)
- `processed: bool = False` — LLM đã xử lý chưa (dùng để retry)

---

## Phase 2 — Storage Engine (storage/sqlite.py → Supabase PostgreSQL)

**Triết lý cốt lõi của Database:**
1. **FinOps (Token Management):** Ngăn hệ thống gọi AI vô ích cho các tin cũ/trùng lặp -> "Cái phanh" đốt tiền.
2. **Deduplication (Gác cổng):** Dùng ID băm (SHA-256) làm Unique Key, đảm bảo dữ liệu 100% sạch qua `ON CONFLICT DO NOTHING`.
3. **Structured Analytics:** Biến text RSS thô thành "Tài sản dữ liệu" có cấu trúc (Sentiment, Impact) để truy vấn trend sau này.
4. **Retry Cap:** `retry_count` giới hạn AI retry ở 3 lần/bài, tránh đốt rate limit khi Groq outage.

**Schema bảng `articles`:**
```sql
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,           -- SHA-256(url)
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,    -- ISO 8601 UTC
    summary TEXT,
    sentiment REAL,
    market_impact TEXT,
    key_takeaway TEXT,
    scraped_at TEXT NOT NULL,
    processed INTEGER DEFAULT 0,   -- 0=False, 1=True
    retry_count INTEGER DEFAULT 0  -- Cap ở 3, tránh đốt rate limit
);
```

**Hàm cốt lõi:**
- `init_db()` → tạo bảng nếu chưa có
- `upsert_article(article) -> bool` → True nếu là tin mới, False nếu trùng (ON CONFLICT DO NOTHING)
- `get_unprocessed() -> List[Article]` → lấy bài có `processed=0 AND retry_count < 3`
- `mark_processed(id, sentiment, market_impact, key_takeaway)` → cập nhật sau LLM
- `increment_retry(id)` → tăng retry_count khi AI fail, cap ở 3 lần

**DB Persistence:** Supabase PostgreSQL hosted (free tier, 500MB). Không cần GitHub Artifacts. Loại bỏ race condition và rủi ro mất data do retention 7 ngày.

---

## Phase 3 — RSS Scraper (scrapers/generic_rss.py)

**Mục tiêu:** Thu thập tin tức mới từ các RSS feed.

**Thư viện:** `feedparser`

**Luồng xử lý:**
1. Đọc danh sách URLs từ `config/sources.yaml`
2. Dùng `feedparser.parse(url)` cho từng feed
3. Với mỗi entry:
   - Bỏ qua nếu không có `link` hoặc `published_parsed`
   - Tạo `Article` object → Pydantic validate
   - Bỏ qua nếu ValidationError
4. Trả về `List[Article]`

**Edge case:** feedparser không raise exception khi URL fail — phải check `feed.bozo`.

---

## Phase 4 — Insight Extractor (processors/insight_extractor.py)

**Mục tiêu:** Biến tin thô thành tín hiệu có giá trị.

**API:** Groq API, model `llama3-8b-8192` (primary), `llama3-70b-8192` (fallback)

**System Prompt:**
```
You are CryptoSentinel, a hyper-specialized autonomous crypto analyst.
Your persona:
- Skeptical, data-driven, and technical.
- Ignore social media noise and marketing hype.
- Do not recognize 'revolutionary' or 'game-changing' as valid descriptors.
- Focus on liquidity flows and verifiable unit economics.
- Tone: Cold, precise, and concise. Never friendly or polite.

Analyze the following news title and summary. Return ONLY a valid JSON object:
{
  "sentiment": <float from -1.0 to 1.0>,
  "market_impact": <"bullish" | "bearish" | "neutral">,
  "key_takeaway": <max 20 words, must be a skeptical, evidence-based insight, no hype>
}
Do not include any explanation or markdown.
```

**JSON Parse Strategy:**
1. Dùng Groq JSON mode nếu có (`response_format={"type": "json_object"}`)
2. Nếu không — regex extract `{...}` từ response string
3. Normalize `market_impact`: `.lower().strip()`, nếu không match → "neutral"
4. Nếu parse fail hoàn toàn → log warning, `processed` vẫn là `False` để retry sau

**Rate Limiting:** `time.sleep(2)` sau mỗi API call

---

## Phase 5 — Telegram Notifier (utils/notifier.py)

**Mục tiêu:** Phân phối tín hiệu đến người dùng.

**Điều kiện gửi:** `market_impact in ["bullish", "bearish"]`. Neutral → bỏ qua (noise reduction).

**Disclaimer:** Mỗi tin nhắn Telegram có dòng cuối: `⚠️ AI-generated insight. Verify data before trading.` để cảnh báo LLM có thể hallucinate số liệu.

**Format tin nhắn:**
```
📈 BULLISH | The Block

Bitcoin rises to $70K as spot ETF inflows hit $500M daily

Sentiment: +0.82
Key: "Institutional inflows signal sustained demand at current price levels"

Source: https://...
```

**Rate Limiting:** `time.sleep(2)` giữa mỗi lần gửi

**Secrets:** `BOT_TOKEN`, `CHAT_ID` từ environment variables

---

## Phase 6 — Orchestration (main.py + scraper.yml)

### main.py — Luồng tuyến tính:
```python
MAX_BATCH_SIZE = 20  # Giới hạn số bài xử lý AI mỗi lần chạy

1. init_db()
2. articles = scrape_all_feeds()          # Phase 3
3. new_count = 0
   for article in articles:
       is_new = upsert_article(article)   # Phase 2
       if is_new: new_count += 1
4. unprocessed = get_unprocessed()[:MAX_BATCH_SIZE]  # Phase 2 + batch limit
5. for article in unprocessed:
       success = analyze_article(article) # Phase 4
       if success:
           mark_processed(article.id, ...)        
           if article.market_impact != NEUTRAL:
               send_telegram(article)     # Phase 5
               sleep(2)
       else:
           increment_retry(article.id)    # Tăng retry, cap ở 3 lần
6. log(f"Done. New: {new_count}, Processed: {len(unprocessed)}")
```

### .github/workflows/scraper.yml:
```yaml
name: CryptoSentinel Scraper
on:
  schedule:
    - cron: '0 * * * *'  # Mỗi 1 giờ
  workflow_dispatch:       # Chạy thủ công khi cần

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }

      - run: pip install -r requirements.txt

      - run: python main.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}
```

> **Lưu ý:** Không cần download/upload artifact nữa. Supabase PostgreSQL giữ state vĩnh viễn.

---

## Edge Cases & Xử lý Rủi ro

| Rủi ro | Xử lý |
|---|---|
| RSS feed down | `feedparser` return empty → log warning, skip |
| Groq rate limit (429) | `time.sleep(2)` + `MAX_BATCH_SIZE=20` giới hạn số call/lần chạy |
| LLM JSON parse fail | `increment_retry()` tăng counter, cap ở 3 lần rồi bỏ qua vĩnh viễn |
| Telegram rate limit | `time.sleep(2)` giữa mỗi lần gửi |
| DB mất state | Không còn rủi ro — Supabase PostgreSQL hosted, persistent vĩnh viễn |
| `market_impact` case mismatch | normalize `.lower().strip()` trước khi compare |
| LLM hallucinate số liệu | Disclaimer `⚠️ AI-generated insight` trên mỗi tin Telegram |

---

## File Inventory

| File | Vai trò |
|---|---|
| `models/article.py` | Data Contract — Pydantic validation |
| `storage/sqlite.py` | Storage Engine — upsert + dedup |
| `scrapers/generic_rss.py` | RSS Ingestion |
| `processors/insight_extractor.py` | Groq LLM analysis |
| `utils/notifier.py` | Telegram delivery |
| `main.py` | Orchestrator |
| `config/sources.yaml` | RSS feed list |
| `requirements.txt` | Python dependencies |
| `.env.example` | Secrets template |
| `.github/workflows/scraper.yml` | GitHub Actions schedule |
| `docs/monitor_agent.md` | Giám sát chất lượng hệ thống |

**Tổng cộng: 11 file. Không có file nào thừa.**
