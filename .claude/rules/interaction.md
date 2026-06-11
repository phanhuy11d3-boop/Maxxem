# Rules: Agent Interaction & Conflict Resolution

Quy định cách các Agent cộng tác và xử lý bất đồng. `CLAUDE.md` luôn thắng
nếu file này mâu thuẫn với hiến pháp hiện tại.

## 1. Product Flow

- DEX-first path: Ingestion Scout -> Signal Engineer/Analyst -> DB Auditor ->
  Notifier Broadcaster -> Ops Manager.
- RSS/LLM news path là legacy/secondary. Không dùng nó để quyết định số liệu
  trong DEX price-move alert.
- Không tạo file state trung gian mới nếu runtime chưa thật sự đọc/ghi file đó.

## 2. Challenge Protocol

- Khi Auditor reject một alert hoặc migration, agent sở hữu phần đó phải đưa
  bằng chứng: config, raw API/DB row, dedup key, status, hoặc test.
- Không giả định có model tie-break không tồn tại trong codebase. Với DEX alert,
  nguồn quyết định là dữ liệu thị trường + rule engine, không phải LLM.

## 3. Error Handling

- Nếu bot "im", luôn chạy `py -3 scripts/diagnose_dexscreener.py` trước khi
  chỉnh threshold hoặc prompt.
- Nếu pipeline lỗi hệ thống, Ops Manager kiểm tra env, DB, scheduler, source
  health, rồi mới kết luận lỗi sản phẩm.
- Live commands có thể gửi Telegram hoặc ghi production DB phải được nêu rõ.

## 4. Security

- Tuyệt đối không chia sẻ `BOT_TOKEN`, `DATABASE_URL`, hoặc API key trong docs,
  tests, comments, memory, hay log.
- Các agent không cần token chỉ được thấy trạng thái đã mask hoặc 4 ký tự cuối
  nếu thật sự cần đối chiếu.
