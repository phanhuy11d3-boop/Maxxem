---
name: env-quirks-diagnostics
description: Environment quirks when running diagnose scripts (sandbox blocks 5432, cp1252 console, 8B ignores JSON mode and wraps output in code fences)
metadata:
  type: project
---

Quirks môi trường khi chạy bộ scripts diagnose của signal-analyst (ghi nhận 2026-06-10):

1. **Sandbox của Bash tool chặn outbound Postgres port 5432** → `psycopg2.OperationalError: timeout expired` tới Supabase pooler. Phải chạy lại với sandbox tắt thì mới kết nối được.
2. **Console Windows là cp1252** → prefix `PYTHONIOENCODING=utf-8` trước mọi lệnh `py -3 scripts/diagnose_*.py` (Bash tool dùng cú pháp POSIX nên prefix env var trực tiếp được).
3. **8B (FAST_MODEL) KHÔNG tôn trọng `response_format={"type":"json_object"}` một cách chặt chẽ** — quan sát được output bọc trong code fence ```json dù đã bật JSON mode. Production `triage_articles()` (`processors/insight_extractor.py` dòng ~128) gọi `json.loads` trực tiếp, không strip fence → khi 8B trả fenced JSON, parse throw → rơi vào fallback anti-miss (all high_impact). Recall an toàn nhưng triage bị vô hiệu hóa âm thầm → tốn token 70B. Triệu chứng trong log: "Triage error → fallback anti-miss".

**Why:** mất thời gian chẩn đoán lại các lỗi môi trường này mỗi lần audit; điểm 3 còn là nghi can chính khi thấy "triage 8B loại 0 bài".
**How to apply:** áp dụng prefix/sandbox ngay từ lệnh đầu. Khi thấy triage rejection rate = 0, kiểm tra log fallback anti-miss trước khi nghi ngờ TRIAGE_PROMPT; fix ứng viên (chưa làm, cần user duyệt) là strip code fence trước json.loads. Liên quan [[baseline-impact-distribution]].
