# QA Checklist (Monitor Agent)

> **Triết lý lõi:** Lean, FinOps, Deterministic. Zero bloat.

## 1. 🔴 Bắt buộc (Code Review Rules)
- `market_impact` LUÔN là Enum, KHÔNG PHẢI string.
- Bắt buộc dùng `normalize_market_impact()` khi parse data từ LLM.
- `DATABASE_URL` và `API_KEY` tuyệt đối không hardcode, phải dùng `os.environ`.
- DB queries luôn dùng parameter binding (`%s`) để chống SQL Injection.
- Gọi LLM và gửi Telegram LUÔN phải kẹp `time.sleep(2)` để chặn rate limit.
- Parse JSON LLM phải có `try/except`. Lỗi thì gọi `increment_retry()`.

## 2. 🟢 Kiến trúc (Architecture Rules)
- **Storage:** Supabase PostgreSQL (Không dùng SQLite, bỏ hoàn toàn GitHub Artifacts).
- **LLM:** Groq Llama 3 (`temperature=0.0`, ép JSON mode).
- **Orchestration:** Đúng 1 file `main.py` làm nhạc trưởng. Tự động hoá qua GitHub Actions cronjob.
- **Tính Module:** 1 file = 1 chức năng duy nhất (Single Responsibility).

## 3. 🚨 Integration Smoke Test (Go Live)
- [ ] `main.py` chạy từ đầu đến cuối không crash.
- [ ] Mọi tin tức mới được lưu an toàn vào Supabase, không lọt tin trùng.
- [ ] Telegram nhận tin chuẩn định dạng (chỉ gửi Bullish/Bearish, chặn Neutral).
- [ ] Các tin nhắn Telegram đều đính kèm dòng cảnh báo AI Disclaimer.

## 4. 🔵 DB Layer Rules (Bắt buộc — thêm sau khi phát hiện gap)
- Storage engine file LUÔN được đặt tên theo backend thực tế (đang dùng PostgreSQL → file phải là `postgres.py`, không phải `sqlite.py`).
- Column types LUÔN dùng PostgreSQL native: `TIMESTAMPTZ` (không phải `TEXT`), `BOOLEAN` (không phải `INTEGER`).
- **Kết nối Database PHẢI dùng `psycopg2.pool.SimpleConnectionPool`** — tuyệt đối không được mở/đóng TCP connection mỗi lần gọi hàm (anti-pattern của SQLite local).
- Mọi hàm thao tác DB ĐỀU phải có `try/except psycopg2.OperationalError` kèm `conn.rollback()` và `putconn()` trong `finally`.
- Không được làm crash `main.py` chỉ vì một thao tác DB lẻ (upsert, mark, retry) thất bại — log lỗi và tiếp tục.

## 5. 🟠 Infrastructure Migration Rules
- Khi nâng cấp infrastructure (ví dụ: local → cloud, SQLite → PostgreSQL), **BẮt BUỘC audit lại toàn bộ** các design pattern liên quan — không được copy-paste nguyên xi code cũ.
- Checklist migration tối thiểu:
    - [ ] File name và module name phản ánh đúng backend mới.
    - [ ] Data types được chuyển sang native type của backend mới.
    - [ ] Connection pattern phù hợp với backend mới (pool cho cloud, file handle cho local).
    - [ ] Error handling được bổ sung cho failure modes của backend mới (network, timeout, auth).
    - [ ] Tất cả imports trong các file khác được cập nhật đồng bộ.
