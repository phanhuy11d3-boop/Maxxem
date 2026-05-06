# Insight Extractor — JSON Output Schema (chính thức)

> File này là nguồn sự thật duy nhất (single source of truth) cho output contract của Analyst.
> Mọi thay đổi schema phải cập nhật đồng thời: file này + `SYSTEM_PROMPT_BATCH` + `Article` model + `postgres.py`.

---

## Tier 1 — Triage Response (model: `llama-3.1-8b-instant`)

**Input:** Mảng tiêu đề bài báo (JSON array of strings)

**Output:**
```json
{
  "results": [true, false, true]
}
```

- `true` = `high_impact`: bài cần đưa qua Tier 2 phân tích sâu.
- `false` = `low_impact`: bài bị loại, không gửi Telegram, không tốn Tier 2 tokens.
- Thứ tự phần tử khớp với thứ tự input.

---

## Tier 2 — Batch Analysis Response (model: `llama-3.3-70b-versatile`)

**Input:**
```json
[
  {"id": "uuid-string", "title": "...", "summary": "... (max 500 chars)"}
]
```

**Output:**
```json
{
  "results": [
    {
      "id": "uuid-string",
      "sentiment": 0.75,
      "market_impact": "bullish",
      "key_takeaway": "Max 20 words, phải chứa ít nhất 1 con số cụ thể từ input.",
      "narrative_tag": "BTC_ETF",
      "affected_tokens": ["$BTC", "$ETH"],
      "urgency": "breaking"
    }
  ]
}
```

### Field Definitions

| Field | Type | Constraint |
|---|---|---|
| `id` | `string` | UUID khớp với `Article.id` |
| `sentiment` | `float` | Range: `-1.0` (cực bearish) → `1.0` (cực bullish) |
| `market_impact` | `string` | Enum: `bullish` \| `bearish` \| `neutral` |
| `key_takeaway` | `string` | Tối đa 20 từ; phải có ít nhất 1 con số từ input; cấm: *revolutionary, game-changer, moon, explode* |
| `narrative_tag` | `string` | Enum: `AI` \| `RWA` \| `DePIN` \| `BTC_ETF` \| `Regulation` \| `Hack` \| `Macro` \| `Other` |
| `affected_tokens` | `array[string]` | Tối đa 3 token, format `$SYMBOL` (ví dụ: `["$BTC", "$SOL"]`); `[]` nếu không rõ |
| `urgency` | `string` | Enum: `breaking` \| `important` \| `context` |

### Urgency Rules
- `breaking`: hacks, exploit, regulatory ban/approval, exchange collapse.
- `important`: funding >$50M, mainnet launch, major partnership.
- `context`: phân tích, update nhỏ, market context.

---

## Mapping vào `Article` model

```python
article.sentiment       = float(res["sentiment"])
article.market_impact   = normalize_market_impact(res["market_impact"])
article.key_takeaway    = str(res["key_takeaway"])[:300]
article.narrative_tag   = str(res.get("narrative_tag", "Other"))
article.affected_tokens = res.get("affected_tokens", [])[:3]
article.urgency         = str(res.get("urgency", "context"))
article.processed       = True
```
