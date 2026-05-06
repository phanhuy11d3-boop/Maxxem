# Skill: High-Engagement Broadcasting (Broadcaster)

> **Mục tiêu:** Biến Telegram thành kênh signal cao cấp. Tin nhắn phải Đẹp - Đủ - Đúng.

## 1. Visual Hierarchy (Cấu trúc bản tin)

**Header Line:**
```
[urgency_prefix] [impact_emoji] BULLISH/BEARISH | Source
```
- `urgency = breaking`  → tiền tố: `🔴 BREAKING |`
- `urgency = important` → tiền tố: `⚡ IMPORTANT |`
- `urgency = context`   → không có tiền tố

**Meta Line (ngay dưới header):**
```
🏷 <narrative_tag>  🪙 $TOKEN1 $TOKEN2
```
- `narrative_tag` hiển thị nếu khác `Other`.
- `affected_tokens` format: `$SYMBOL` mỗi token.

**Body:**
- Tiêu đề bài báo (plain text, HTML-escaped).
- `Sentiment: +0.75` (số thực từ LLM).
- `Key: "<key_takeaway>"` — in nghiêng.

**Footer:**
- `🔗 Source link` (hyperlink HTML).
- `⚠️ AI-generated insight. Verify data before trading.`

## 2. Phân tầng kênh (Free vs. Premium)
- **Free channel** (`CHAT_ID`): gửi tất cả bài `is_actionable` (bullish + bearish).
- **Premium channel** (`PREMIUM_CHAT_ID`): gửi thêm full signal gồm `key_takeaway`, `affected_tokens`, `urgency`.
- Nếu `PREMIUM_CHAT_ID` không được cấu hình → chỉ gửi free channel, không báo lỗi.

## 3. Delivery Logic (FinOps & Rate Limit)
- Kiểm tra `is_actionable` trước khi gửi (chỉ gửi Bullish/Bearish, lọc Neutral).
- Khoảng cách giữa các tin nhắn: 2 giây (tuân thủ Telegram rate limit ~20 msg/min per bot).
- Tham chiếu schema output: `.claude/skills/insight-extractor/reference.md`.
