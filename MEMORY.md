# CryptoSentinel - AI Memory & Lessons Learned

> File này được tạo ra để ghi nhận những sai sót, hiểu lầm của AI (Antigravity) trong quá trình pair-programming cùng USER. 
> Mục tiêu: Tự kiểm điểm, tránh tái phạm và tuân thủ tuyệt đối triết lý dự án.

## 1. Bài học về Quản lý File & Kiến trúc Lean
* **Vấn đề:** Tiến hành tạo nhiều file cùng lúc (dù có nằm trong plan) mà chưa giải thích cặn kẽ mục đích, khiến USER lo ngại dự án bị phình to, sinh "file rác" làm loãng scope và tốn token.
* **Cách khắc phục:** 
    * Trước khi tạo ra bất kỳ file nào, **BẮT BUỘC** phải báo cáo và giải thích rõ cho USER: File đó chứa gì? Tại sao bắt buộc phải có? Nó có giúp tiết kiệm token hay không?
    * Tuyệt đối không tự ý đẻ thêm các file cấu hình, helper, utilities lắt nhắt nằm ngoài bản thiết kế `implementation_plan.md` đã chốt.

## 2. Bài học về Môi trường Thực thi (Terminal)
* **Vấn đề:** Chạy ghép lệnh Terminal bằng toán tử `&&` (`pip install ... && python ...`) trên môi trường Windows PowerShell dẫn đến lỗi cú pháp. Không kiểm tra kỹ môi trường cục bộ (thiếu Path cho Python/Pip) mà vẫn cố chạy test tự động.
* **Cách khắc phục:** 
    * Ghi nhớ hệ điều hành của USER là Windows (PowerShell). Khi cần chạy lệnh, phải dùng đúng cú pháp của PowerShell (chạy từng dòng hoặc dùng dấu `;`).
    * Nhận thức rõ môi trường đích thực sự chạy hệ thống này là Serverless (GitHub Actions), không nên lạm dụng tool chạy lệnh cục bộ nếu môi trường máy USER chưa thiết lập sẵn, tránh gây ra những lỗi nhiễu không đáng có.

## 3. Bài học về Giao tiếp & Token FinOps
* **Vấn đề:** Có lúc giải thích quá dài dòng thay vì tập trung thẳng vào logic kỹ thuật.
* **Cách khắc phục:**
    * Giữ câu trả lời súc tích, đi thẳng vào trọng tâm (Talk is cheap, show me the code).
    * Giữ các file code ngắn gọn (chia nhỏ module một cách hợp lý nhưng không làm nát dự án), đảm bảo mỗi lần đưa code cho AI đọc lại tốn ít token context nhất có thể.

## 4. Bài học về Nâng cấp DB từ SQLite → Supabase (PostgreSQL)
* **Vấn đề phát hiện:** Khi refactor từ SQLite sang Supabase, AI đã bê nguyên xi 4 lỗi kiến trúc từ tư duy cũ:
    1. **Tên file** vẫn là `sqlite.py` dù code bên trong dùng `psycopg2` → vi phạm Single Responsibility.
    2. **Data Types lỗi thời:** Dùng `TEXT` cho timestamps thay vì `TIMESTAMPTZ`, dùng `INTEGER` cho boolean thay vì `BOOLEAN` — đây là SQLite workaround, không phải PostgreSQL native type.
    3. **Connection Anti-pattern (chí mạng nhất):** Mở và đóng kết nối TCP cloud mỗi lần gọi hàm. Với 100 bài báo sẽ tạo ra 100 TCP handshake tới cloud → cực chậm, có thể bị Supabase rate limit. Phải dùng Connection Pool.
    4. **Thiếu Network Error Handling:** Không có `try/except psycopg2.OperationalError` trong thao tác DB. Cloud DB có thể bị timeout mạng, không thể để crash cứng `main.py`.
* **Cách khắc phục bắt buộc:**
    * Đổi tên file thành `postgres.py` sau khi chuyển storage engine.
    * Luôn dùng native PostgreSQL types (`TIMESTAMPTZ`, `BOOLEAN`, `TEXT`) thay vì SQLite workarounds.
    * Bắt buộc dùng `psycopg2.pool.SimpleConnectionPool` để tái sử dụng kết nối.
    * Bọc tất cả thao tác DB trong `try/except` với ít nhất `psycopg2.OperationalError`.
    * **Quy tắc vàng:** Khi nâng cấp từ local storage → cloud storage, PHẢI audit lại toàn bộ các pattern thiết kế, không được copy-paste nguyên xi.

## 5. Bài học về Gap trong Hệ thống Giám sát (Monitor Agent)
* **Vấn đề phát hiện:** `monitor_agent.md` chỉ tập trung giám sát lỗi LLM và Data Format, nhưng hoàn toàn thiếu:
    * Rules cho Database layer (types, connection pattern, error handling).
    * Nguyên tắc giám sát Network Resilience khi dùng Cloud services.
    * Bất kỳ rule nào về cách refactor/nâng cấp infrastructure.
* **Cách khắc phục:** `monitor_agent.md` phải được cập nhật để bổ sung checklist giám sát DB layer và network resilience tương đương với rigor hiện có cho LLM layer.

## 6. Bài học về CI Guard False Positive (Comment chứa Pattern nhạy cảm)
* **Vấn đề phát hiện:** File `storage/postgres.py` có một dòng **comment ví dụ** dạng:
  `# postgresql://postgres.[ref]:[password]@...`
  → CI Guard quét thấy chuỗi `postgresql://` trong `*.py` file → **kết luận sai** là đang hardcode credentials → Block deploy.
* **Nguyên nhân gốc rễ:** Rule bảo mật trong `ci_guard.yml` chỉ kiểm tra sự xuất hiện của chuỗi ký tự, không phân biệt được đó là **code thật** hay **comment ví dụ**.
* **Cách khắc phục:**
    * Khi viết comment ví dụ về connection strings, URL, credentials: **KHÔNG được dùng đúng nguyên ký tự bị chặn** (ví dụ: `postgresql://`). Thay thế bằng chuỗi trung tính như `postgres-protocol://` hoặc `<db-url>`.
    * Đây là quy tắc áp dụng cho **toàn bộ mọi loại comment, docstring, và string ví dụ** trong code.
* **Rule bổ sung vào `monitor_agent.md`:** Checklist Code Review phải bổ sung mục kiểm tra pattern nhạy cảm trong cả comment, không chỉ trong code thực thi.

## 7. Bài học về Model Decommissioning (Khai tử Model)
* **Vấn đề phát hiện:** Hệ thống báo `LLM: 20 errors` mặc dù API Key đúng.
* **Nguyên nhân cốt lõi:** Model `llama3-8b-8192` bị Groq khai tử. API trả về lỗi 400 nhưng hệ thống chỉ ghi nhận là "LLM Error", dẫn đến giả định sai là lỗi API Key.
* **Cách khắc phục:** 
    * Cập nhật sang model mới nhất (`llama-3.3-70b-versatile`).
    * **Nguyên tắc kiến trúc:** Trong các hệ thống Agent, không nên phụ thuộc vào 1 model duy nhất. Nên có cơ chế cấu hình model qua biến môi trường hoặc có danh sách fallback.
* **Rule bổ sung vào `monitor_agent.md`:** Khi AI lỗi hàng loạt với code 400, phải kiểm tra tính khả dụng của Model ID trước khi yêu cầu người dùng đổi API Key.

## 8. Bài học về Lỗi Logic Local và Lỗ hổng Giám sát (Audit Blindspots)
* **Vấn đề phát hiện:** AI ở phiên trước đã sửa file `main.py` ở local (xoá biến `article.processed = True` trong RAM) nhưng không commit, gây lệch pha nghiêm trọng giữa local và GitHub. Hơn nữa, cả 3 lớp giám sát đều "mù" trước lỗi này:
    1. **Audit Agent (`audit_agent.py`)** chỉ quét Database (trạng thái tĩnh), không bắt được lỗi logic runtime.
    2. **AI Reviewer (`check_response.py`)** có khả năng bắt lỗi logic nhưng bị AI và USER quên không gọi thủ công.
    3. AI hỗ trợ (là tôi) khi debug đã bỏ sót file `check_response.py` vì chỉ tập trung vào các file USER tag.
* **Nguyên nhân gốc rễ:** 
    * `mark_processed()` chỉ cập nhật DB, nhưng không cập nhật state của object `article` trong RAM, khiến hàm `is_actionable` (chạy ngay sau đó) bị false và chặn việc gửi Telegram.
    * Quá tin tưởng vào Audit Agent chạy bằng cơm (DB checker) mà quên mất các lỗi logic luồng (flow logic).
* **Cách khắc phục & Rule mới:**
    * **Tuyệt đối không để lại "code rác/code nháp" (unstaged changes) ở local.** Đã sửa là phải test và commit/revert dứt điểm.
    * Phải nhớ rằng cập nhật DB (`mark_processed`) **không đồng nghĩa** với việc object trong bộ nhớ Python tự động được cập nhật. Phải set state bằng tay (`article.processed = True`) nếu hàm sau đó cần dùng tới nó.
    * **Luôn rà soát toàn bộ thư mục `scripts/`** trước khi kết luận hệ thống thiếu tính năng, tránh bỏ quên các Agent đã được xây dựng từ trước.

## 9. Bài học về Giao tiếp & Thống nhất Kế hoạch (Planning first)
* **Vấn đề phát hiện:** Tự tiện tạo ra các file script mới (như `db_viewer.py`, `db_actionable.py`) để giải quyết tình huống thay vì đọc/phân tích mã nguồn, thảo luận và lên kế hoạch (plan) với USER trước. Điều này làm rác thư mục, đi ngược lại triết lý Lean Architecture và phá vỡ luồng pair-programming.
* **Cách khắc phục:**
    * Tuyệt đối KHÔNG ĐƯỢC tự ý tạo file mới, viết script nháp, hay sửa code khi chưa bàn bạc và được sự đồng ý của USER.
    * Khi USER đặt câu hỏi (VD: "Tại sao lỗi?"), công việc của AI là **phân tích tĩnh (static analysis)** mã nguồn hiện tại, log, và database để suy luận, sau đó trình bày nguyên nhân. Không được tự lấy cớ "để xem cho rõ" rồi đẻ thêm file.
    * Mọi file sinh ra ngoài `implementation_plan.md` đều bị coi là rác nếu không được thông qua.

## 11. Bài học về Tối ưu hóa Chi phí (Token FinOps)
* **Vấn đề:** Việc gọi model lớn (70B) cho từng bài báo riêng lẻ gây lãng phí token hệ thống và chi phí không cần thiết cho các tin tức rác.
* **Cách khắc phục & Quy tắc vàng:**
    * **Tiered LLM:** Luôn sử dụng model nhỏ (8B) để lọc (Triage) tin tức trước. Chỉ những tin "High Impact" mới được gửi tới model lớn (70B).
    * **Batch Processing:** Gom nhiều bài báo vào một lần gọi API (Batch) để dùng chung System Prompt, giúp tiết kiệm đến 70-80% lượng prompt tokens.
    * **JSON Mode:** Tận dụng tính năng Native JSON của API thay vì dùng các câu lệnh giải thích dài dòng trong prompt để ép kiểu.

*(File này sẽ liên tục được AI chủ động cập nhật nếu phát sinh thêm bất cứ sai sót nào trong quá trình xây dựng CryptoSentinel).*
