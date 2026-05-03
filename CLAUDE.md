# CryptoSentinel — The Multi-Agent Constitution (v3.0)

> [!IMPORTANT]
> Dự án đã chuyển sang kiến trúc **Multi-Agent Orchestration**. Mọi thay đổi code phải tuân thủ "Hợp đồng công cụ" (Tool Schema) và không được phá vỡ tính cô lập (Isolation) của các Agent.

## 📍 Nguyên tắc vận hành (Agentic Rules)
1. **Tool-Centric**: Code Python là "Công cụ", không phải "Trình điều khiển". AI Agent là người điều khiển.
2. **JSON Protocol**: Mọi giao tiếp giữa các Agent và Tools phải thông qua JSON có cấu trúc (Pydantic validated).
3. **Progressive Disclosure**: Agent chỉ được cấp Context tối thiểu cần thiết để hoàn thành Task.
4. **Human-in-the-loop**: Mọi thay đổi về hạ tầng hoặc config hệ thống phải được đề xuất qua Agent và được con người phê duyệt.

## 📍 Danh mục Agent (Specialists)
- `/scout`: Tìm kiếm tin tức mới, lọc trùng lặp (Scout-Agent).
- `/analyze`: Phân tích sâu nội dung, đánh giá tác động (Analyst-Agent).
- `/audit`: Kiểm định chất lượng dựa trên Golden Dataset (Auditor-Agent).
- `/broadcast`: Định dạng và gửi thông báo Telegram (Broadcaster-Agent).
- `/run`: Chạy toàn bộ Workflow (Orchestrator).

## 📍 Quy tắc tương tác & Xử lý xung đột
- **Challenge Protocol**: Auditor-Agent có quyền bác bỏ kết quả của Analyst-Agent nếu độ lệch (variance) so với Golden Dataset > 20%.
- **Rewind Logic**: Khi gặp lỗi Tool, Agent phải quay lại trạng thái (state) trước đó, log lỗi chi tiết và thử lại tối đa 2 lần trước khi báo cáo cho Orchestrator.
- **Explanatory Style**: Orchestrator phải luôn giải thích lý do tại sao chọn Sub-agent hoặc Tool đó trong log thực thi.

## 📍 Lệnh phát triển (Build & Test)
- **Install**: `pip install -r requirements.txt`
- **Unit Tests**: `pytest tests/unit`
- **Integration**: `pytest tests/integration`
- **Legacy Run**: `python main.py --legacy`
- **Agentic Run**: `python main.py --agentic`
