# CryptoSentinel — The Multi-Agent Constitution (v3.0)

> [!IMPORTANT]
> Dự án đã chuyển sang kiến trúc **Multi-Agent Orchestration**. Mọi thay đổi code phải tuân thủ "Hợp đồng công cụ" (Tool Schema) và không được phá vỡ tính cô lập (Isolation) của các Agent.

## 📍 Nguyên tắc vận hành (Agentic Rules)
1. **Tool-Centric**: Code Python (`main.py`) đóng vai trò là "Công cụ thực thi". Orchestrator-Agent là người điều khiển.
2. **JSON Protocol**: Mọi giao tiếp giữa các Agent và Tools phải thông qua JSON có cấu trúc.
3. **Multi-Agent Flow**: Scout (Cào tin) -> Analyst (Phân tích/The Block Style) -> Auditor (Kiểm định) -> Broadcaster (Telegram).

## 📍 Lệnh phát triển (Build & Test)
- **Install**: `pip install -r requirements.txt`
- **Unit Tests**: `pytest tests/unit`
- **Legacy Run**: `python main.py --legacy` (Luồng tuyến tính v2.2)
- **Agentic Run**: `python main.py --agentic` (Luồng có sự giám sát của Orchestrator v3.0)
