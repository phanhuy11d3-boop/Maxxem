# CryptoSentinel — AI Memory & Lessons Learned

> Bài học vận hành cho AI khi làm việc trong repo này. Lịch sử chi tiết thời
> news/LLM nằm trong git history (trước commit pivot 2026-06-12) — đọc làm
> bằng chứng lịch sử, không phải nguồn sự thật hiện tại.

## 0. Pivot DEX-only (2026-06-12) — bài học lớn nhất

* Dự án từng là bot news RSS + LLM sentiment. Toàn bộ đường đó đã bị XÓA
  big-bang theo lệnh operator: không news, không LLM, không bullish/bearish.
* **Bài học:** đừng để tàn dư hai sản phẩm sống chung một codebase — identity
  lẫn lộn làm mọi quyết định sau đó chậm và sai. Khi pivot, xóa hẳn.
* Bảng `articles` cũ vẫn nằm trong Supabase (đóng băng). Code chỉ dùng bảng
  `signals`. Đừng "tiện tay" migrate/drop.

## 1. Quản lý File & Kiến trúc Lean

* Trước khi tạo file mới, giải thích rõ: chứa gì, tại sao bắt buộc phải có.
* Không đẻ file helper/state lắt nhắt mà runtime không thật sự đọc/ghi.

## 2. Môi trường thực thi

* Máy operator là Windows + PowerShell: không dùng `&&`; console cp1252 hay
  crash unicode → prefix `PYTHONIOENCODING=utf-8` cho mọi script in tiếng Việt/emoji.
* Production chạy 2 ca: Task Scheduler local (ngày) + GH Actions shift loop
  (đêm). `py -3 main.py` là LIVE-FIRE: ghi DB thật + gửi Telegram thật.

## 3. Giao tiếp & quyết định

* Operator (Huy) ưu tiên tốc độ-ra-tin và tính đọc-nhanh của alert; giải thích
  ngắn, đi thẳng vào logic, tiếng Việt.
* "Bot im" không mặc nhiên là bug: chạy `py -3 scripts/diagnose_dexscreener.py`
  trước, "no pair crossed thresholds" là trạng thái lành mạnh.
