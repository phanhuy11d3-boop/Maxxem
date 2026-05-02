# CryptoSentinel — Guide for AI Assistant (v2.1)

> [!CAUTION]
> **QUY TẮC BẢO MẬT TUYỆT ĐỐI:**
> - **KHÔNG BAO GIỜ** hardcode API Key vào mã nguồn.
> - **KHÔNG BAO GIỜ** commit `.env` hoặc file nhạy cảm lên Git.
> - Đọc API Key từ biến môi trường (`os.environ`).

## 📍 Định hướng cốt lõi
- **Stack:** Python 3.11+, Groq API (Llama 3), Supabase (PostgreSQL), GitHub Actions, Telegram.
- **Triết lý:** Pipeline tuyến tính, serverless, cực kỳ tối giản (Lean).
- **Tra cứu chi tiết:** `implementation_plan.md` (Kế hoạch), `docs/monitor_agent.md` (Checklist QA).

## 📍 Hard Rules (Bắt buộc tuân thủ)
1. **Dữ liệu:** Dùng `pydantic` để validate, `market_impact` bắt buộc là Enum.
2. **Database:** Dùng `ON CONFLICT (id) DO NOTHING` trên ID (Sanitized URL hash) để chống trùng lặp.
3. **FinOps:** Dùng `processed` (0/1) và `MAX_BATCH_SIZE=20` để kiểm soát chi phí API.
4. **Rate Limit:** Luôn có `time.sleep(2)` khi gọi LLM hoặc Telegram.
5. **Deduplication:** URL phải được sanitize (chặt query params) trước khi hash ID.
6. **Log:** Dùng `logging` với format chuẩn, không dùng `print` bừa bãi.

## 📂 Inventory (Trạng thái dự án)
| File | Vai trò | Trạng thái |
|---|---|---|
| `models/article.py` | Data Contract + MarketImpact Enum | ✅ Done |
| `storage/sqlite.py` | Supabase Engine (Retry count, Persistent) | ✅ Done |
| `scrapers/generic_rss.py` | RSS Ingestion (feedparser) | ✅ Done |
| `processors/insight_extractor.py` | Groq LLM (Persona: CryptoSentinel) | ✅ Done |
| `utils/notifier.py` | Telegram Delivery (Disclaimer included) | ✅ Done |
| `main.py` | Orchestrator tuyến tính | ✅ Done |
| `config/sources.yaml` | RSS Feed URL list | ✅ Done |
| `requirements.txt` | Python Dependencies | ✅ Done |
| `.env.example` | Secrets template | ✅ Done |
| `.github/workflows/scraper.yml` | GitHub Actions cron | ✅ Done |
