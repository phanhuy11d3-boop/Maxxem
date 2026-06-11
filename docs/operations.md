# Operations — QA, Smoke Test & Outbox

> Checklist giám sát pipeline **trading-grade** (cron 1 phút, stale 30 phút, Telegram outbox, telemetry tách kênh).

Triết lý: **deterministic**, ưu tiên recall (miss tin là lỗi nghiêm trọng). Chi tiết kiến trúc → [`docs/architecture.md`](architecture.md).

---

## 1. Biến môi trường bắt buộc & tùy chọn

**Bắt buộc:** `DATABASE_URL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `BOT_TOKEN`, `CHAT_ID`. (Trên Actions, `LLM_BASE_URL` phải là URL public — localhost không reach được từ runner.)

**Khuyến nghị vận hành:**

- `ENABLE_OPS_TELEMETRY` — `1`/`true`/`on` để nhận **heartbeat** và **admin alert**; **`0`/không set** để tắt hoàn toàn (mặc định trong workflow hiện tại có thể là tắt).
- `ADMIN_CHAT_ID`, `HEARTBEAT_CHAT_ID` — chỉ được dùng khi telemetry bật; **never** được trùng `CHAT_ID` (guard trong code).

**Premium / APIs:**

- `PREMIUM_CHAT_ID` — optional; tin `breaking|important` gửi thêm bản mở rộng.
- `UW_API_KEY`, `ARKHAM_API_KEY` — optional; không có → `fast_signals` bỏ qua nguồn tương ứng, pipeline vẫn chạy.

---

## 2. 🔴 Rules bắt buộc (code review)

- `market_impact` trong runtime Python luôn qua **`MarketImpact`** + `normalize_market_impact()` khi đọc từ LLM/DB string.
- `DATABASE_URL`: không hardcode; binding queries (`%s`) cho mọi SQL user-controlled.
- **CI Guard / secret patterns:** không để trong comment/docstring **Python** các chuỗi nhạy cảm (`postgresql://`, `gsk_`, …); dùng placeholder kiểu `<db-url>` (xem MEMORY & repo CI).
- **`low_confidence`:** phải được **persist DB** và đọc lại khi `get_tg_dispatch_queue` để nhãn `[?]` không bị mất giữa enqueue và dispatch.

---

## 3. 🟢 Smoke test — go-live

- [ ] `init_db()` / migration chạy trên Postgres đích (`ALTER` IF NOT EXISTS xong).
- [ ] **`py -3 main.py`** (Windows) hoặc **`python main.py`** (CI) → không crash full pipeline.
- [ ] Scraped → `SELECT` có row mới, dedup không nhân đôi cùng `id`.
- [ ] Tin **bullish/bearish**: xuất hiện trên Telegram với **`Source time (ICT) | Sent | Lag`** khi `published_from_source`; dòng **`Confidence: [?] low`** khi `low_confidence`.
- [ ] Neutral: **không** vào queue gửi; `tg_status` không kẹt `pending`.
- [ ] Actionable backlog: **`_dispatch_tg_queue`** gọi **đầu** và **cuối** run — tin mới không nằm kẹt nếu run trước crash giữa LLM và send.
- [ ] Sau **30 phút**, actionable chưa gửi → `tg_status='expired'`, không retry vô hạn.
- [ ] **Telemetry:** với flag tắt, không có heartbeat trên Telegram; khi bật, không spam `CHAT_ID`.

---

## 4. Outbox / SLA quan sát

- Heartbeat (khi bật) in: **`pending_count`**, `failed_count`, `expired_count_60m`, **`oldest_pending_age_min`**.
- Code gửi **admin alert** khi **`oldest_pending_age_min >= 24`** (risk trước deadline stale).
- `send_telegram` báo SLA khi **`SLA_SECONDS` (120s)** breached (telemetry phải bật và `ADMIN_CHAT_ID` hợp lệ).

---

## 5. DB layer checklist

- `storage/postgres.py` chỉ Postgres + pool; không engine file DB song song trong pipeline chính.
- Types native: **`TIMESTAMPTZ`**, **`BOOLEAN`**.
- Pool: `SimpleConnectionPool`; không mở kết nối mới từng lệnh trong hot path production.
- Mọi hành động DB: `OperationalError` → log + rollback + `putconn`, không được crash `main` vì một lần retry DB.

---

## 6. LLM troubleshooting

- Lỗi hàng loạt HTTP **400** từ LLM gateway → kiểm tra **model ID**/`response_format`/prompt contract trước khi kết luận sai key.
- `LLM_MISSING_RESULTS` alert: batch 70B thiếu object theo id — không bump `retry`; bài gắn `low_confidence`.

---

## 7. Telegram & rate-limit (sản phẩm)

- **Không** throttle cố định giữa từng tin signal chỉ để “giữ yên” kênh; khi burst, ưu tiên **delivery** (TG API có thể vẫn trả 429 — xử lý qua retry outbox/`mark_tg_attempt`).
- Cron 1 phút + concurrency `cancel-in-progress: false` → tránh overlap run dài có thể tạo hàng chờ song song — theo dõi duration trong heartbeat.
