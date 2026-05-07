# CryptoSentinel — manual cho AI / operator (AIOS-lite)

Hệ thống có playbook `.claude/` (agents + skills) cho mô tả vai trò; **production mặc định** là `main.py` legacy. Chỉ agentic khi gọi `--agentic` (có fallback legacy).

## Nguyên tắc vận hành (chốt ý)

1. **Cadence 1 phút** — không downgrade về cron giờ trong production.
2. **Stale 30 phút** — tin cũ không gửi Telegram; AI queue cũng không xử lý.
3. **Recall-first** — ưu tiên gửi có nhãn **`[?]` / low confidence** hơn là bỏ sót; Tier-1 không bị triage 8B làm im lặng.
4. **Outbox Telegram** — `tg_status` (`pending` / `sent` / `failed` / `expired`); atomic `mark_processed_with_tg`.
5. **Telemetry** — heartbeat / admin chỉ khi **`ENABLE_OPS_TELEMETRY`** bật; **không** trùng `CHAT_ID`.
6. **`low_confidence` lưu DB** — dispatch queue đọc lại để format Telegram không mất nhãn.

Chi tiết: [`docs/architecture.md`](docs/architecture.md).

## Lệnh

| Mục đích | Lệnh |
|---|---|
| Pipeline mặc định | `python main.py` hoặc `py -3 main.py` (Windows) |
| Ép legacy | `python main.py --legacy` |
| Agentic | `python main.py --agentic` |
| Unit tests | `pytest tests/unit` hoặc `py -3 -m pytest tests/unit` |

## Cấu trúc playbook

- `.claude/agents/` — Scout / Analyst / Auditor / Broadcaster / Orchestrator (hướng dẫn vai trò).
- `.claude/skills/` — SOP ingestion / insight / audit / broadcast.
- **`storage/state.json`** — snapshot metadata cuối run; **state tin thật nằm Postgres**.
