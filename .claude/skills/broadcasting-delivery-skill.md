# Skill: High-Engagement Broadcasting (Broadcaster)

> **Mục tiêu:** Biến Telegram thành kênh tin tức cao cấp. Tin nhắn phải Đẹp - Đủ - Đúng.

## 1. Visual Hierarchy (Cấu trúc bản tin)
- **Header:** Dùng Emoji phản ánh "vibe" thị trường:
  - 📈 BULLISH (Xanh) | 📉 BEARISH (Đỏ) | 🔍 NEUTRAL (Xám).
- **Body:** 
  - Tiêu đề bôi đậm (**Title**).
  - Tóm tắt ý chính trong 2-3 gạch đầu dòng sắc bén.
  - Nhấn mạnh Token/Protocol bằng lệnh `code` (ví dụ: `$BTC`, `$SOL`).
- **Footer:** 
  - `🔗 Nguồn: [Link]`
  - `⚠️ Cảnh báo: AI-generated insight. Verify data.`

## 2. Delivery Logic (FinOps & Rate Limit)
- Kiểm tra `MarketImpact` trước khi gửi (Chỉ gửi Bullish/Bearish).
- Tuân thủ giới hạn 20 tin/batch để tiết kiệm token và tránh bị Telegram ban.
- Khoảng cách giữa các tin nhắn: 2-3 giây để tránh bị bóp tương tác.
