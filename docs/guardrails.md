# Guardrails — ràng buộc vận hành & nội dung

Được enforce chính qua `CLAUDE.md`, logic DEX trong [`scrapers/dexscreener.py`](../scrapers/dexscreener.py), các hằng **`TRIAGE_PROMPT`**, **`SYSTEM_PROMPT_BATCH`** trong [`processors/insight_extractor.py`](../processors/insight_extractor.py), logic **`main.py`**, và format [`models/article.py`](../models/article.py). Không dùng ElizaOS trong pipeline Python.

---

## 1. Không hallucination số liệu

- LLM chỉ phân tích từ `title` và `summary` đã ingest.
- Thiếu dữ liệu → **`market_impact: neutral`**, không bịa mới.
- Alert DEXScreener không dùng LLM để bịa diễn giải: số liệu phải đến trực tiếp từ API pair (`priceChange`, `volume`, `liquidity`, `txns`).

---

## 2. No overhype (từ cấm & takeaway)

Key takeaway: không dùng *revolutionary, game-changer, moon*, … như trong system prompt.

---

## 3. Recall-first vs “neutral drop”

- **Telegram chỉ nhận bài directional:** `bullish` / `bearish` (`Article.is_actionable`).
- **`neutral`** sau 70B: **không** enqueue Telegram — không phải bug, là “không có tín hiệu hướng giá”.
- **Triage Tier-2:** bài bị đánh giá low-impact vẫn vào batch 70B với **`low_confidence`** (anti-miss).
- LLM batch **thiếu id**: đóng **`processed`** + **`low_confidence`** + neutral auto-close (không tăng `retry_count`).

---

## 4. Toàn vẹn dữ liệu scrape

[`models/article.py`](../models/article.py): title/url/source/published_at không hợp lệ → reject trước DB.

Meta thời gian:

- **`published_from_source`**: báo Telegram có hay không dòng `Source time (ICT)` — nếu RSS không có timestamp, scraper set `FALSE` và ẩn dòng đó.

---

## 5. Dedup

[`storage/postgres.py`](../storage/postgres.py): `id = SHA-256(URL đã sanitize)`; `ON CONFLICT DO NOTHING`. Story-level dedup (trùng nội dung khác URL) không có trong lõi hiện tại.

DEX pair alerts dùng `Article.dedup_key` theo `{chain}:{pair}:{horizon}:{direction}:{time_bucket}` để cùng một DEXScreener URL có thể alert lại sau cooldown mà không spam từng phút.

---

## 6. Anti-stale & trust

**30 phút** từ `published_at` / `scraped_at`:

- không đưa vào queue AI đã có `processed=FALSE` quá hạn (`get_unprocessed`);
- actionable chưa gửi kịp được **`expired`** — không ép gửi tin trading “quá cửa”.

---

## 7. Telemetry & SLA

- **Lag** được hiển thị trong mỗi tin (ICT khi có nguồn).
- `utils/notifier.py`: **`SLA_SECONDS` (120)** — cảnh báo qua admin khi vượt (telemetry phải bật).
- Heartbeat chứa KPI outbox; tắt bằng `ENABLE_OPS_TELEMETRY`.

---

## Sync tài liệu

Đổi prompt hoặc contract JSON → cập nhật song song:

1. Prompts trong `insight_extractor.py`
2. [`.claude/agents/signal-analyst.md`](../.claude/agents/signal-analyst.md)
3. `Article` fields + Postgres columns nếu thêm cờ mới (`low_confidence` đã có cột DB).

Đổi DEX alert contract → cập nhật song song:

1. [`config/dexscreener.yaml`](../config/dexscreener.yaml)
2. [`scrapers/dexscreener.py`](../scrapers/dexscreener.py)
3. [`scripts/diagnose_dexscreener.py`](../scripts/diagnose_dexscreener.py)
4. [`.claude/skills/dexscreener-watchlist/SKILL.md`](../.claude/skills/dexscreener-watchlist/SKILL.md)
5. [`tests/unit/test_dexscreener_alerts.py`](../tests/unit/test_dexscreener_alerts.py)
