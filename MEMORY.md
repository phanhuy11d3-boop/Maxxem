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

*(File này sẽ liên tục được AI chủ động cập nhật nếu phát sinh thêm bất cứ sai sót nào trong quá trình xây dựng CryptoSentinel).*
