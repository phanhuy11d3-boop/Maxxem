---
name: env-quirks-diagnostics
description: Environment quirks when running diagnose scripts (sandbox blocks 5432, cp1252 console)
metadata:
  type: project
---

Quirks môi trường khi chạy diagnose scripts (ghi nhận 2026-06-10, vẫn đúng với v3 DEX-only):

1. **Sandbox của Bash tool chặn outbound Postgres port 5432** → `psycopg2.OperationalError: timeout expired` tới Supabase pooler. Phải chạy lại với sandbox tắt thì mới kết nối được.
2. **Console Windows là cp1252** → prefix `PYTHONIOENCODING=utf-8` trước mọi lệnh `py -3 scripts/diagnose_*.py` (Bash tool dùng cú pháp POSIX nên prefix env var trực tiếp được).
3. **Scripts không tự đọc `.env`** → từ bare shell phải nạp env trước (`set -a; . ./.env; set +a`), nếu không sẽ gặp "Chưa cấu hình DATABASE_URL".

**Why:** mất thời gian chẩn đoán lại các lỗi môi trường này mỗi lần audit.
**How to apply:** áp dụng prefix/nạp env/sandbox ngay từ lệnh đầu. (Mục cũ về 8B/triage/LLM đã xóa cùng pivot DEX-only 2026-06-12.)
