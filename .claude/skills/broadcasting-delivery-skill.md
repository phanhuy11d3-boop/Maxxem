# Skill: High-Engagement Broadcasting (Broadcaster)

> **Mục tiêu:** Telegram là kênh **signal** — đủ thông tin, đúng format HTML, hiển thị **lag** làm KPI sống.

Tham chiếu code thật: `models/article.py::format_telegram_html` + `utils/notifier.py::send_telegram`.

---

## 1. Visual hierarchy (HTML / parse_mode HTML)

**Header (có urgency + low confidence):**

```text
[🔴 BREAKING |] [📈/📉] [?] BULLISH | Source
```

- `urgency = breaking|important` → tiền tố như trong code.
- **`[?]`** + dòng **`Confidence: [?] low`** khi `article.low_confidence` (persist DB — dispatch phải đọc được).

**Meta (optional):**

```text
🏷 <narrative_tag>   🪙 $BTC $ETH
```

**Title:** plain, đã escape HTML.

**Thời gian (ICT) — chỉ khi `published_from_source`:**
```text
⏱ Source time (ICT): HH:MM - dd/mm/yyyy | Sent: HH:MM | Lag: Xm
```
Nếu thời gian nguồn là fallback không tin cậy → ẩn block (field `published_from_source=False`).

**Body:**

- `Sentiment: ±0.xx`
- `Key: "..."` (italic)

**Footer:**

- Hyperlink **Source link**
- `⚠️ AI-generated insight...`

---

## 2. Kênh Free vs Premium

- **Free (`CHAT_ID`):** `format_telegram_html` như trên — mọi `is_actionable`.
- **Premium (`PREMIUM_CHAT_ID`):** thêm khối signal cho `breaking`/`important` qua `_build_premium_message` (không được fail silently che free channel).

---

## 3. Delivery & outbox (trading-grade)

- **Không** tự giới hạn “tối đa 20 tin mỗi batch” ở lớp broadcast — đó là kích thước **LLM batch**, không phải cap sản phẩm.
- Gửi thực tế qua **`_dispatch_tg_queue`**: chỉ các row `tg_status in (pending, failed)` chưa `expired`, chưa vượt `tg_attempts` max — xem [`docs/architecture.md`](../../../../docs/architecture.md).
- Tin **`tg_status=expired`** hoặc ngoài cửa sổ stale: **không** gửi (anti-stale).

---

## 4. SLA & Telegram API

- Mỗi lần gửi được đo lag; notifier có thể `send_admin_alert` khi SLA nội bộ breached (**chỉ khi** ops telemetry & admin chat valid).
- **Không** thêm delay cố định giữa tin chỉ để “làm yên feed” trong code production — burst là kỳ vọng khi volatility.

---

## 5. Schema LLM output

Đồng bộ với [`.claude/skills/insight-extractor/reference.md`](reference.md).
