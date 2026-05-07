# Insight Extractor — JSON contract (canonical)

Đổi prompts hoặc parser → sửa **đồng thời** file này, `processors/insight_extractor.py`, `Article`, `storage/postgres` (nếu thêm cột DB).

---

## Tier 1 — Triage (`llama-3.1-8b-instant`)

**Áp dụng:** chỉ articles **Tier-2** trong `main.py` (Tier-1 + fast-signal bỏ qua bước này).

**Input (user message — JSON string):**

```json
[
  {"idx": 0, "title": "..."},
  {"idx": 1, "title": "..."}
]
```

`idx` là số nguyên **0..n-1** thứ tự trong batch triage (map 1-1 tới thứ tự list Python).

**Output (strict JSON object):**

```json
{
  "results": [
    {"idx": 0, "high_impact": true},
    {"idx": 1, "high_impact": false}
  ]
}
```

**Runtime Python:** `triage_articles(...) -> Dict[str, bool]` — key là **`Article.id`** (SHA-256), value là `high_impact`.  
Parser map `idx` → article rồi gán `id`. **Anti-miss:** exception, thiếu quá `TRIAGE_ANTI_MISS_RATIO`, hoặc id không khớp → fallback coi mọi bài `True`.

**Lưu ý:** Không dùng `List[bool]` thuần (dễ lệch vị trí khi model trả sai thứ tự).

---

## Tier 2 — Batch analysis (`llama-3.3-70b-versatile`)

**Input:** JSON array

```json
[
  {"id": "<article_id_sha256>", "title": "...", "summary": "..."}
]
```

**Output:** một object

```json
{
  "results": [
    {
      "id": "<same article_id>",
      "sentiment": 0.75,
      "market_impact": "bullish",
      "key_takeaway": "Max 20 words, có số từ input khi có thể",
      "narrative_tag": "BTC_ETF",
      "affected_tokens": ["$BTC", "$ETH"],
      "urgency": "breaking"
    }
  ]
}
```

### Field definitions

| Field | Type | Note |
|---|---|---|
| `id` | string | **Byte-for-byte** `Article.id` |
| `sentiment` | float | -1.0 … 1.0 |
| `market_impact` | string | Chỉ `bullish` \| `bearish` \| `neutral` (prompt cấm synonym) |
| `key_takeaway` | string | Max ~20 từ, tone khô, cấm hype words trong prompt |
| `narrative_tag` | string | `AI` \| `RWA` \| `DePIN` \| `BTC_ETF` \| `Regulation` \| `Hack` \| `Macro` \| `Other` |
| `affected_tokens` | string[] | Tối đa 3, dạng `$SYMBOL` |
| `urgency` | string | `breaking` \| `important` \| `context` |

### Post-processing (Python, không nằm trong JSON model)

- `normalize_market_impact()` map synonym LLM hay lệch contract (ví dụ positive/negative) → enum.
- **`low_confidence`** (bool) — **không** do LLM trả; runtime gắn khi:
  - Tier-2 bị triage `high_impact=False` nhưng vẫn analyze (path anti-miss),
  - `|sentiment| < LOW_CONF_SENTIMENT_ABS_THRESHOLD` (main),
  - hoặc **missing** object trong `results` cho một id (Vector 3b) → neutral + auto-closed + processed.

`low_confidence` **phải persist** qua `mark_processed_with_tg(..., low_confidence=...)` để `get_tg_dispatch_queue` render `[?]` đúng.

---

## BatchOutcome (phân loại lỗi cụm)

Chúng ta không retry vô tri:

| Giá trị | Ý nghĩa | Hành vi main |
|---|---|---|
| `OK` | Parse + đủ contract | Tiếp tục ghi DB / enqueue TG |
| `TRANSIENT_FAIL` | Rate limit / network | `increment_retry` toàn chunk (cron sẽ thử lại) |
| `STRUCTURAL_FAIL` | JSON/prompt không ăn | Không bump retry — admin alert để fix contract |

---

## Mapping vào Article (conceptual)

```text
sentiment, market_impact, key_takeaway, narrative_tag, affected_tokens, urgency  ← LLM
low_confidence                                                                       ← orchestrator logic
published_from_source                                                                ← scraper (RSS/fast_signals)
processed                                                                            ← sau khi đóng cụm batch hoặc mark DB
tg_status / tg_sent                                                                  ← sau mark_processed_with_tg + dispatcher
```

---

## Mapping vào Postgres

Các cột đồng bộ insight + outbox: `sentiment`, `market_impact`, `key_takeaway`, `narrative_tag`, `affected_tokens`, `urgency`, **`low_confidence`**, **`tg_sent`**, **`tg_status`**, **`tg_attempts`**, timestamps Telegram, `processed`.
