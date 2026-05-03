# CryptoSentinel

Hệ thống tin tức Crypto tự trị — thu thập, phân tích và phân phối tín hiệu thị trường.

## Stack

| Thành phần | Công nghệ |
|---|---|
| Ngôn ngữ | Python 3.11+ |
| LLM | Groq API (Llama 3 8B/70B) |
| Database | Supabase (PostgreSQL hosted) — chỉ [`storage/postgres.py`](storage/postgres.py); runtime không dùng engine DB cục bộ/file |
| Scheduler | GitHub Actions (cron: 1h) |
| Output | Telegram Bot |
| Scraping | feedparser (RSS) |

## Pipeline

```
GitHub Actions (1h)
  → main.py
    → scrapers/generic_rss.py   (Lấy tin từ RSS)
    → models/article.py         (Pydantic validate + Sanitize URL)
    → storage/postgres.py       (Lưu Supabase + Dedup + Retry Cap)
    → processors/insight_extractor.py  (Groq phân tích - Persona: CryptoSentinel)
    → utils/notifier.py         (Telegram - Chỉ gửi Bullish/Bearish)
```

## Cấu trúc thư mục (Lean Architecture)

```
crypto-sentinel/
├── main.py                     # Nhạc trưởng điều phối
├── models/article.py           # Định nghĩa dữ liệu (Data Contract)
├── scrapers/generic_rss.py     # Cào tin từ RSS
├── processors/insight_extractor.py # AI Engine (Groq Llama 3)
├── storage/postgres.py         # Database Engine (Supabase / psycopg2 pool)
├── utils/notifier.py           # Gửi tin Telegram
├── config/sources.yaml         # Danh sách nguồn RSS
├── docs/
│   └── monitor_agent.md        # Checklist giám sát (Monitor Agent)
├── characters/sentinel.json    # Persona gốc (Reference)
├── .github/workflows/scraper.yml # GitHub Actions Automation
├── requirements.txt            # Thư viện cần cài
├── MEMORY.md                   # Nhật ký sai sót & bài học của AI
└── .env.example                # Mẫu các biến môi trường
```

## Biến môi trường cần thiết

```
DATABASE_URL=   # Supabase Connection String (URI)
GROQ_API_KEY=   # Groq API key
BOT_TOKEN=      # Telegram Bot token
CHAT_ID=        # Telegram Chat/Channel ID
```

## CLI

- `python main.py` — pipeline mặc định (RSS → Postgres → Groq → Telegram).
- `python main.py --legacy` — tương đương mặc định (luôn là luồng tuyến tính trên repo).
- `python main.py --agentic` — chỉ in chú thích roadmap multi-agent trong `.claude/agents/`; **không đổi** pipeline Python.

## Tài liệu quan trọng

- `implementation_plan.md` — Toàn bộ kế hoạch 6 Phase và logic chi tiết.
- `docs/monitor_agent.md` — Quy tắc kiểm duyệt và Smoke Test.
- `MEMORY.md` — Nơi AI lưu lại các bài học để không tái phạm sai lầm.
