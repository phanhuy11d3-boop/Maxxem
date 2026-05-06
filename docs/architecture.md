# Architecture: CryptoSentinel v2 (Python Pipeline)

> Production default vẫn là pipeline tuyến tính. `agentic_runtime.py` là lớp opt-in cho `python main.py --agentic`, map Scout/Analyst/Auditor/Broadcaster vào các Python handler đã kiểm soát và fallback về legacy nếu lỗi nghiêm trọng.

## 1. Sơ đồ Luồng (Linear Pipeline)
```text
[GitHub Actions (cron)] ──> main.py (Orchestrator)
                               │
                               ├─> scrapers/generic_rss.py (Ingest RSS)
                               │
                               ├─> models/article.py (Pydantic Validate)
                               │
                               ├─> storage/postgres.py (Check Dedup)
                               │
                               ├─> processors/insight_extractor.py (Groq LLM)
                               │
                               ├─> storage/postgres.py (Save AI Insight)
                               │
                               └─> utils/notifier.py (Telegram, chỉ gửi bullish/bearish)
```

## 2. Triết lý Database (Storage Engine)
1. **FinOps (Token Management):** Kiểm tra ID bài báo (URL hash) để chặn gọi AI tóm tắt tin cũ -> Tối ưu chi phí cực lớn.
2. **Một backend duy nhất:** Runtime chỉ PostgreSQL (`storage/postgres.py` + pool). Dedup:`INSERT ... ON CONFLICT (id) DO NOTHING` — không có engine file DB trong pipeline hiện tại.
3. **Structured Analytics:** Biến text RSS thô thành "tài sản dữ liệu có cấu trúc" (Sentiment, Impact).

## 3. Dependency Map (Hợp đồng dữ liệu)
- Kiến trúc **Tuyến tính**, không có agent giao tiếp chéo.
- `models/article.py` là trung tâm. MỌI module khác đều phải import data contract từ đây.

```text
main.py
  ├── scrapers/generic_rss.py         ──> models/article.py
  ├── storage/postgres.py             ──> models/article.py
  ├── processors/insight_extractor.py ──> models/article.py
  └── utils/notifier.py               ──> models/article.py
```
