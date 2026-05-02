# Architecture: CryptoSentinel v2 (Python Pipeline)

## 1. Sơ đồ Luồng (Linear Pipeline)
```text
[GitHub Actions (cron)] ──> main.py (Orchestrator)
                               │
                               ├─> scrapers/generic_rss.py (Ingest RSS)
                               │
                               ├─> models/article.py (Pydantic Validate)
                               │
                               ├─> storage/sqlite.py (Check Dedup)
                               │
                               ├─> processors/insight_extractor.py (Groq LLM)
                               │
                               ├─> storage/sqlite.py (Save AI Insight)
                               │
                               └─> utils/notifier.py (Telegram, chỉ gửi bullish/bearish)
```

## 2. Triết lý Database (Storage Engine)
1. **FinOps (Token Management):** Kiểm tra ID bài báo (URL hash) để chặn gọi AI tóm tắt tin cũ -> Tối ưu chi phí cực lớn.
2. **Deduplication (Gác cổng):** Dùng `INSERT OR IGNORE` theo ID để đảm bảo không lọt tin trùng.
3. **Structured Analytics:** Biến text RSS thô thành "tài sản dữ liệu có cấu trúc" (Sentiment, Impact).

## 3. Dependency Map (Hợp đồng dữ liệu)
- Kiến trúc **Tuyến tính**, không có agent giao tiếp chéo.
- `models/article.py` là trung tâm. MỌI module khác đều phải import data contract từ đây.

```text
main.py
  ├── scrapers/generic_rss.py         ──> models/article.py
  ├── storage/sqlite.py               ──> models/article.py
  ├── processors/insight_extractor.py ──> models/article.py
  └── utils/notifier.py               ──> models/article.py
```
