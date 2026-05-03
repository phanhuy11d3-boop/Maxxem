# CryptoSentinel — The AI Operating System (v4.0)

> [!IMPORTANT]
> Hệ thống đã nâng cấp thành **AIOS**. Mọi hoạt động được điều phối bởi Agents thông qua các **Skills** chuyên biệt. Code Python đóng vai trò là công cụ thực thi (Tools/Connections).

## 📍 Kiến trúc AIOS (4 Pillars)
1. **Context**: `.claude/agents/` (Brains) & `.claude/skills/` (Expertise).
2. **Connections**: `scrapers/`, `storage/`, `utils/` (Python Tools).
3. **Capabilities**: Tập hợp các Skills định nghĩa quy trình chuẩn (SOPs).
4. **Cadence**: GitHub Actions & `storage/state.json` (Vòng lặp tự động).

## 📍 Lệnh vận hành (OS Commands)
- **Legacy Run**: `python main.py --legacy` (Pipeline tuyến tính v2.2)
- **Agentic Shell**: `python main.py --agentic` (Shell cho Agent tương tác)
- **Unit Tests**: `pytest tests/unit`
- **System Audit**: `python scripts/audit_agent.py`

## 📍 Cấu trúc thư mục AIOS
- `.claude/agents/`: Định nghĩa cá tính và quyền hạn của các Agent.
- `.claude/skills/`: Chứa các bộ kỹ năng (SOPs) chi tiết.
- `storage/state.json`: Lưu trữ trạng thái hệ thống và bộ nhớ ngắn hạn.
