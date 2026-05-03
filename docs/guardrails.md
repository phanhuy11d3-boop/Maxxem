# Guardrails: Operational Constraints (v2 — Python Pipeline)

> Các quy tắc này được **enforce trong code** qua các hằng `TRIAGE_PROMPT` và `SYSTEM_PROMPT_BATCH`
> trong [`processors/insight_extractor.py`](../processors/insight_extractor.py), cùng logic lọc trong
> [`utils/notifier.py`](../utils/notifier.py). Không liên quan đến ElizaOS hay Twitter API.

---

## 1. Zero Hallucination (Tuyệt đối không ảo giác)

**Áp dụng tại:** `processors/insight_extractor.py`

LLM chỉ được phân tích dựa trên `title` và `summary` của bài báo gốc.
Không được suy diễn, bịa số liệu, hay thêm thông tin ngoài văn bản đầu vào.

Nếu thông tin không đủ để kết luận → `market_impact = "neutral"`, không được đoán mò.

---

## 2. No Overhype (Không phóng đại)

**Áp dụng tại:** System Prompt của Groq LLM

Từ bị cấm trong `key_takeaway`: "revolutionary", "game-changer", "groundbreaking",
"massive", "huge", "moon", "explode", "skyrocket".

`key_takeaway` phải chứa ít nhất 1 con số cụ thể (%, $, số lượng) từ bài báo gốc.
Không có số liệu → LLM phải viết lại câu mà không phóng đại.

---

## 3. Noise Reduction (Giảm nhiễu)

**Áp dụng tại:** `utils/notifier.py`

Chỉ gửi Telegram khi `market_impact` là `"bullish"` hoặc `"bearish"`.
`"neutral"` bị bỏ qua hoàn toàn. Đây là **tính năng**, không phải lỗi.

Lý do: Người dùng nhận Telegram để hành động, không phải để đọc tin trung lập.

---

## 4. Data Integrity (Toàn vẹn dữ liệu)

**Áp dụng tại:** `models/article.py` (Pydantic)

Bài báo thiếu `title`, `url`, hoặc `published_at` → bị loại bỏ trước khi vào DB.
Không có ngoại lệ. Dữ liệu bẩn không được phép đi sâu vào pipeline.

---

## 5. Deduplication (Chống trùng lặp)

**Áp dụng tại:** `storage/postgres.py` (PostgreSQL Supabase duy nhất — dedup không qua DB file cục bộ.)

Mỗi bài báo có ID = SHA-256(URL). `ON CONFLICT (id) DO NOTHING`.
Cùng 1 bài từ nhiều nguồn → chỉ lưu 1 lần. LLM không bao giờ xử lý lại bài đã có.
