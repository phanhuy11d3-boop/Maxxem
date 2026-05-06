# CryptoSentinel — The AI Operating System (v4.0)

> [!IMPORTANT]
> Hệ thống có lớp **AIOS playbook** và runtime agentic opt-in. Production mặc định vẫn là pipeline tuyến tính ổn định; chỉ chạy agentic khi gọi `python main.py --agentic`, và có fallback về legacy.

## 📍 Kiến trúc AIOS (4 Pillars)
1. **Context**: `.claude/agents/` (Brains) & `.claude/skills/` (Expertise).
2. **Connections**: `scrapers/`, `storage/`, `utils/` (Python Tools).
3. **Capabilities**: Tập hợp các Skills định nghĩa quy trình chuẩn (SOPs).
4. **Cadence**: GitHub Actions & `storage/state.json` (Vòng lặp tự động).

## 📍 Lệnh vận hành (OS Commands)
- **Default Run**: `python main.py` (Pipeline tuyến tính ổn định)
- **Legacy Run**: `python main.py --legacy` (Ép pipeline tuyến tính)
- **Agentic Runtime**: `python main.py --agentic` (Scout → Analyst → Auditor → Broadcaster, có fallback legacy)
- **Unit Tests**: `pytest tests/unit`
- **System Audit**: `python scripts/audit_agent.py`

## 📍 Cấu trúc thư mục AIOS
- `.claude/agents/`: Định nghĩa cá tính và quyền hạn của các Agent.
- `.claude/skills/`: Chứa các bộ kỹ năng (SOPs) chi tiết.
- `storage/state.json`: Lưu trữ trạng thái hệ thống và bộ nhớ ngắn hạn.
