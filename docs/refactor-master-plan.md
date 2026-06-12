# CryptoSentinel — DEX-Only Master Plan & Risk Register

> **Trạng thái: ĐÃ THỰC THI big-bang 2026-06-12.** Toàn bộ đường news/RSS/LLM
> đã bị xóa khỏi codebase trong một lần cắt duy nhất (quyết định của operator,
> thay cho strangler migration trong plan cũ). File này là bản plan hoàn chỉnh:
> sản phẩm, kiến trúc, những gì đã làm, risk register, và chiến lược đưa dự án
> lên chuẩn production crypto.

---

## 1. Product Thesis

CryptoSentinel = hệ thống alert biến động giá pair trực tiếp, evidence-rich,
đọc như bảng giá DEXScreener.

User job duy nhất: **biết ngay khi coin mình theo dõi pump/dump, kèm đủ số
liệu để quyết định có mở chart hay không** — trong dưới 2 phút kể từ lúc move
được đo, không cần đọc một chữ tin tức nào.

Không phải sản phẩm:

- tin tức crypto dạng bất kỳ (kể cả "tin nhanh" — đã xóa vĩnh viễn);
- bình luận thị trường do LLM viết;
- nhãn định hướng bullish/bearish — trader nhìn `+12.4%` tự hiểu;
- lời khuyên mua/bán;
- micro-move của pool thanh khoản mỏng.

Thước đo niềm tin của kênh: **mỗi alert đều đáng mở chart**. Kênh im lặng cả
ngày khi thị trường đi ngang là hành vi ĐÚNG.

## 2. Những gì đã thực thi (2026-06-12)

### Đã xóa (zero tàn dư)

| Thành phần cũ | Số phận |
|---|---|
| `scrapers/generic_rss.py`, `config/sources.yaml` (19 RSS feeds) | XÓA |
| `scrapers/fast_signals.py` (UW/Arkham/news APIs) | XÓA |
| `processors/insight_extractor.py` (LLM triage + analysis) | XÓA |
| `agentic_runtime.py`, cờ `--legacy/--agentic` | XÓA |
| `models/article.py` (Article + MarketImpact + sentiment) | XÓA — thay bằng `models/pair_signal.py` |
| 9 diagnose scripts thời news/LLM + `start_9router.vbs` | XÓA — thay bằng 2 script read-only |
| 4 test files thời news + golden dataset | XÓA — thay bằng 2 test files mới (20 tests) |
| Biến env LLM_*, UW/ARKHAM trong .env + workflow | XÓA |
| `openai`, `feedparser` trong requirements | XÓA |
| `characters/`, `references/` (persona cũ) | XÓA |
| Agent-memory gắn với schema/scripts cũ | XÓA, index ghi chú pivot |

### Đã xây mới

- **`models/pair_signal.py`** — `PairSignal`: data contract thuần số liệu,
  `id = sha256(dedup_key)`, render Telegram từ field cấu trúc.
- **`scrapers/dexscreener.py`** — batch fetch theo chain (≤30 pair/request,
  8 pair = 2 HTTP call thay vì 8), symbol-mismatch guard, per-pair override
  cho thresholds/gates, khung mạnh nhất thắng.
- **`storage/postgres.py`** — bảng `signals` cột số liệu cấu trúc (hết thời
  nhét số vào text rồi parse regex); outbox state machine + claim lease giữ
  nguyên thiết kế đã chống gửi-trùng-2-ca thành công.
- **`utils/notifier.py`** — gửi price-board, premium routing theo `is_hot`,
  retry 429, heartbeat ngữ nghĩa mới (`😴 quiet` là trạng thái lành mạnh).
- **`main.py`** — orchestrator 5 phase, không LLM, heartbeat trong `finally`.
- **Format Telegram mới** (tham chiếu các kênh price-alert DEXScreener-style):

  ```text
  🚀 WIF/SOL +12.4% · 1h
  💰 $2.345 · Raydium · Solana
  ⏳ 5m +1.1% | 1h +12.4% | 6h +8.0% | 24h +15.3%
  📊 Vol 1h $850.0K · 💧 Liq $2.4M
  🟢 221 buys · 🔴 109 sells
  🧢 MC $2.2B

  📈 Chart — DEXScreener
  ⏱ 23:04 ICT
  ```

  Nguyên tắc thiết kế: hook ở ký tự đầu (emoji + pair + %), mỗi dòng một lớp
  bằng chứng, đọc xong trong 2 giây, không một chữ opinion.
- **SOP**: 5 subagents + 5 skills viết lại cho DEX-only; guard hook chặn
  live-fire với agent read-only; `validate_pair.py` thay `validate_feed.py`.

### Quyết định kiến trúc đáng nhớ

1. **Bảng `signals` mới, bảng `articles` đóng băng** — không migrate, không
   xóa dữ liệu production. Rollback = revert commit, dữ liệu cũ còn nguyên.
2. **Cooldown nằm trong PK** (`dedup_key` chứa time bucket) — chống spam được
   enforce bởi DB constraint, không phải logic dễ quên.
3. **Direction nằm trong dedup_key** — pump rồi dump trong cùng bucket vẫn
   alert cả hai chiều (đảo chiều là thông tin đắt giá nhất).
4. **Không có chữ nào do máy "nghĩ ra"** — guardrail mạnh nhất chống
   hallucination là không có LLM để hallucinate.

## 3. Risk Register — rủi ro & phòng tránh

| # | Rủi ro | Tác động | Phòng tránh (đã làm) | Còn phải canh |
|---|---|---|---|---|
| R1 | Nhầm pair (search trả token giả mạo cùng tên) | Mất niềm tin nghiêm trọng nhất | Pin `pairAddress` bắt buộc; symbol guard skip+log; `validate_pair.py` trước khi thêm | Pool có thể migrate address — re-validate khi alert lệch chart |
| R2 | Bot im không rõ lý do | Miss move = miss trade | `diagnose_dexscreener.py` phân biệt no-trigger vs broken; heartbeat `😴 quiet` | Chạy diagnose TRƯỚC khi hạ threshold |
| R3 | Spam alert làm chai kênh | User mute kênh = sản phẩm chết | Cooldown bucket trong PK; liquidity/volume gates; per-pair override | Theo dõi alerts/ngày/pair; tune bằng signal-analyst |
| R4 | Gửi alert giá nguội | User vào lệnh theo giá đã đổi | Expire 30 phút trước mọi lần dispatch; SLA 120s có cảnh báo | Cadence gap 2 ca (xem R6) |
| R5 | Gửi trùng giữa 2 ca production | Kênh trông cẩu thả | `claim_tg_send_slot` row-lock + lease 180s (đã bắt bug thật 2026-06-11) | Mọi send mới PHẢI qua claim |
| R6 | GH Actions throttle cron → dead air | Move trong gap chết stale | Shift loop 5h30 + tự dispatch ca kế; skill `cadence-check` đo coverage | `WORKFLOW_PAT` hết hạn thì handover gãy |
| R7 | DEXScreener API đổi schema / rate-limit / sập | Mất nguồn dữ liệu duy nhất | `_num()` chịu data bẩn; batch giảm request 4×; fail từng phần không sập pipeline | Single-source risk: cân nhắc nguồn dự phòng (GeckoTerminal) ở phase sau |
| R8 | Pool thanh khoản mỏng bị thao túng để bait alert | Alert "đúng số liệu" nhưng vô nghĩa | `min_liquidity_usd` gate + cờ DYOR < $100k | Threshold mặc định chưa chắc hợp meme coin — tune theo dữ liệu thật |
| R9 | Schema migration phá DB sống | Downtime + mất lịch sử | Chỉ additive, idempotent; bảng cũ đóng băng không đụng | Không bao giờ DROP khi chưa có lệnh operator |
| R10 | Tàn dư context cũ lái AI/agent sai hướng | SOP drift về news-first | Xóa code + config + memory cũ; CLAUDE.md ghi rõ pivot; banned-words test | Memory mới phải ghi ngày + bối cảnh |
| R11 | Secret lộ trong docs/log | Sự cố bảo mật | Placeholder-only; agent chỉ thấy 4 ký tự cuối; rules/interaction.md | Giữ thói quen khi viết doc mới |
| R12 | Format HTML vỡ vì ký tự lạ trong symbol | Telegram reject message | `html.escape` mọi field text; test format | Symbol unicode bất thường của meme coin mới |

## 4. Chiến lược chuẩn production-crypto (lộ trình sau big-bang)

### Giai đoạn A — Ổn định (tuần đầu)

1. Chạy 2 ca song song, theo dõi `diagnose_outbox.py` mỗi ngày: `expired=0`,
   p95 lag ≤120s.
2. Tune threshold theo dữ liệu thật: majors (WBTC/WETH/SOL) hạ threshold,
   meme (WIF/BONK/PEPE) giữ hoặc nâng — bằng per-pair override, có bằng chứng.
3. Xác nhận handover GH Actions ↔ local không còn dead-air gap > 30 phút.

### Giai đoạn B — Chất lượng tín hiệu

1. **Severity score** thay `is_hot` nhị phân: điểm từ move% × volume ×
   liquidity tier × txns imbalance → route kênh + emoji mức độ.
2. **Daily digest** 1 tin/ngày: top movers 24h của watchlist (giữ kênh sống
   khi thị trường đi ngang mà không spam).
3. **Buy/sell imbalance highlight**: 80/20 buys đáng chú ý hơn 50/50 —
   thêm 1 dòng khi lệch mạnh.

### Giai đoạn C — Mở rộng nguồn (vẫn DEX-only)

1. Nguồn dự phòng đối chiếu (GeckoTerminal API) để khử R7 single-source.
2. Watchlist động: tự đề xuất pair trending (operator duyệt, không tự thêm).
3. New-listing watch: pair mới list có volume bùng nổ (high-risk, opt-in,
   luôn gắn DYOR).

### Nguyên tắc xuyên suốt

- Mọi feature mới phải qua Business Bar trong `CLAUDE.md`.
- Không feature nào được phép làm chậm đường alert chính.
- Quiet là trạng thái hợp lệ — không bao giờ tune để bot "có gì đó để nói".

## 5. Kill Criteria

- Nếu phải thêm lời bình cho alert "có giá trị" → sản phẩm đã trượt hướng.
- Nếu user không tin pair identity và con số → dừng feature, sửa data.
- Nếu quiet period không giải thích được → dừng tăng trưởng, sửa observability.
- Nếu kênh bắt đầu giống kênh tin tức → refactor này coi như thất bại.

## 6. Việc operator cần làm tay (ngoài repo)

1. **GitHub Secrets**: có thể xóa `LLM_API_KEY`, `UW_API_KEY`, `ARKHAM_API_KEY`
   (workflow không còn tham chiếu — để lại không hại nhưng nên dọn).
2. **Task Scheduler**: task chạy `start_9router.vbs` lúc logon (9Router LLM
   gateway) không còn cần — gỡ để đỡ tốn RAM. Task `CryptoSentinel-Pipeline`
   giữ nguyên.
3. **Supabase**: bảng `articles` giữ làm lịch sử; muốn dọn thì export rồi drop
   — chỉ làm tay, code không bao giờ tự làm.
