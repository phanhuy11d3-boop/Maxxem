# Skill: Precision Data Ingestion (Scout)

> **Mục tiêu:** Đảm bảo 100% dữ liệu đầu vào là tin tức crypto chất lượng, không rác, không trùng.

## 1. Triage Rule (Lọc tin)
- **Priority 1 (Must Have):** Thay đổi chính sách (Regulation), Hack/Exploit, Listing/Delisting sàn lớn (Binance, Coinbase), gọi vốn khủng (>10M$).
- **Priority 2 (Should Have):** Partnership lớn, cập nhật Mainnet/Upgrade, tin tức về các Narrative đang hot (AI, RWA, DePIN).
- **Ignore (Rác):** Tin dự đoán giá cá nhân, tin quảng cáo (Shilling), tin lặp lại từ các nguồn khác nhau mà không có thông tin mới.

## 2. Source Validation
- Kiểm tra tính hợp lệ của RSS Feed thông qua `feed.bozo`.
- Nếu phát hiện nguồn tin thường xuyên đưa tin sai lệch, đánh dấu "Low Reliability" để Auditor tăng cường kiểm tra.

## 3. Tool Interaction
- Sử dụng `python main.py scrape` để lấy dữ liệu.
- Kiểm tra số lượng `new_count` để báo cáo cho Orchestrator.
