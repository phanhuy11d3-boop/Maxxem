# Rules: Agent Interaction & Conflict Resolution

Quy định cách các Agent cộng tác và xử lý bất đồng.

## 1. Luồng truyền tin (Information Flow)
- Scout → Orchestrator → Analyst → Auditor → Orchestrator → Broadcaster.
- Runtime hiện tại truyền dữ liệu trung gian qua `RuntimeContext` trong `agentic_runtime.py`.
- Không tạo file state trung gian mới nếu runtime chưa thật sự đọc/ghi file đó.

## 2. Cơ chế Thách thức (Challenge Protocol)
- **Khi Auditor REJECT**: Orchestrator PHẢI yêu cầu Analyst giải thích logic phân tích.
- Nếu Analyst bảo lưu quan điểm: không có model “405B tie-break” trong codebase — dùng re-prompt 70B/siết input, hoặc can thiệp manual; pipeline production là deterministic Python.

## 3. Quản lý lỗi (Error Handling)
- Nếu một Agent không phản hồi sau 30s: Orchestrator sẽ thử lại với nhiệt độ (temperature) cao hơn (0.2 thay vì 0).
- Nếu Tool trả về lỗi hệ thống: Scout-Agent có nhiệm vụ kiểm tra file `.env` hoặc kết nối DB trước khi báo cáo lỗi nghiêm trọng.

## 4. Bảo mật (Security)
- Tuyệt đối không chia sẻ `BOT_TOKEN` cho bất kỳ Agent nào ngoại trừ Broadcaster.
- Các Agent khác chỉ được thấy 4 số cuối của Token (nếu cần log).
