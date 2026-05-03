# Skill: Anti-Hallucination & Security Audit (Auditor)

> **Mục tiêu:** Bảo vệ uy tín của CryptoSentinel. Đảm bảo tin tức chính xác, không ảo giác, không FUD.

## 1. Fact-Check Loop
- **Verify Numbers:** Kiểm tra số liệu (vốn hóa, số tiền hack, % tăng trưởng). Nếu con số quá phi thực tế -> Yêu cầu Analyst kiểm tra lại.
- **Context Match:** Đảm bảo `key_takeaway` phản ánh đúng nội dung bài báo, không "suy diễn" quá đà.
- **Source Integrity:** Kiểm tra xem bài báo có dẫn nguồn từ X (Twitter), báo lớn hay chỉ là tin đồn.

## 2. AI Hallucination Guard
- Phát hiện các thực thể (Entity) bị LLM tự chế ra.
- Nếu Analyst trả về kết quả "Bullish" cho một tin tức rõ ràng là "Bearish" (như tin bị hack) -> Chặn ngay lập tức và gắn cờ lỗi logic.

## 3. Security Check
- Phát hiện các dấu hiệu của tin lừa đảo (Phishing) hoặc dự án Scam trong nội dung bài báo để cảnh báo người dùng.
