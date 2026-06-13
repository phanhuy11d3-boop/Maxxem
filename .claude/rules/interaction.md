# Rules: Agent Interaction & Conflict Resolution

Quy định cách các Agent cộng tác và xử lý bất đồng. `CLAUDE.md` luôn thắng
nếu file này mâu thuẫn với hiến pháp hiện tại.

## 1. Product Flow

- Sản phẩm là DEX-only: Ingestion Scout (scanner/watchlist) -> Signal Analyst
  (ngưỡng/rule) -> DB Auditor (signals + outbox) -> Notifier Broadcaster
  (format + delivery) -> Ops Manager (cadence/CI).
- KHÔNG có đường RSS/news/LLM nào trong sản phẩm. Mọi số liệu trong alert đến
  từ DEXScreener API; hướng đi của giá là dấu của change_pct, không phải nhãn.
- Không tạo file state trung gian mới nếu runtime chưa thật sự đọc/ghi file đó.

## 2. Challenge Protocol

- Khi Auditor reject một alert hoặc thay đổi schema, agent sở hữu phần đó phải
  đưa bằng chứng: config, raw API/DB row, dedup key, tg_status, hoặc test.
- Nguồn quyết định cho mọi tranh chấp về alert là dữ liệu thị trường + rule
  engine deterministic. Không có model tie-break nào tồn tại trong codebase.

## 3. Error Handling

- Nếu bot "im" hoặc ít tin, luôn dùng skill `/health-sweep` — không chạy
  script đơn lẻ thay thế. "Không pair nào vượt ngưỡng" là trạng thái lành mạnh.
- Nếu pipeline lỗi hệ thống, Ops Manager kiểm tra env, DB, scheduler/cadence,
  rồi mới kết luận lỗi sản phẩm. Outbox xem bằng `scripts/diagnose_outbox.py`.
- Live commands có thể gửi Telegram hoặc ghi production DB (`py -3 main.py`,
  `py -3 utils/notifier.py --live`, preflight `--live`) phải được nêu rõ trước
  khi chạy. Subagent read-only bị guard hook chặn các lệnh này.

## 4. Security

- Tuyệt đối không chia sẻ `BOT_TOKEN`, `DATABASE_URL`, hoặc API key trong docs,
  tests, comments, memory, hay log.
- Các agent không cần token chỉ được thấy trạng thái đã mask hoặc 4 ký tự cuối
  nếu thật sự cần đối chiếu.
