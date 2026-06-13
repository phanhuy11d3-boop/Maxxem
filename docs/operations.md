# Operations — QA, Smoke Test & Outbox (v3 DEX-only)

> Checklist vận hành pipeline alert giá **trading-grade**: cadence 1 phút,
> stale 30 phút, outbox chống trùng, telemetry tách kênh.

Triết lý: **deterministic**. Một alert sai (nhầm pair, giá nguội, số bịa) phá
niềm tin nhanh hơn mười alert đúng xây được.

---

## 1. Biến môi trường

**Bắt buộc:** `DATABASE_URL`, `BOT_TOKEN`, `CHAT_ID`.

**Khuyến nghị vận hành:**

- `ENABLE_OPS_TELEMETRY` — `1`/`true`/`on` để nhận heartbeat + admin alert;
  `0`/không set = tắt hoàn toàn.
- `ADMIN_CHAT_ID`, `HEARTBEAT_CHAT_ID` — chỉ dùng khi telemetry bật; **không
  bao giờ** trùng `CHAT_ID` (guard trong code).
- `PREMIUM_CHAT_ID` — optional; nhận move nóng (`is_hot`: m5 ≥8% hoặc bất kỳ
  khung ≥15%) HOẶC confidence ≥ `scoring.premium_min_score` (config). Kênh
  chính luôn nhận mọi alert.
- `DIGEST_CHAT_ID` — optional; nơi gửi daily top-movers digest (fallback
  `CHAT_ID`).

---

## 2. 🔴 Rules bắt buộc (code review)

- `DATABASE_URL` không hardcode; mọi SQL bind tham số (`%s`).
- **CI Guard / secret patterns:** không để chuỗi nhạy cảm (`postgresql://`,
  token pattern) trong comment/docstring Python; dùng placeholder `<db-url>`.
- `low_liquidity` phải persist DB và đọc lại lúc dispatch — nhãn DYOR không
  được mất giữa enqueue và send.
- Không thêm trường opinion (sentiment, bullish/bearish, urgency chữ) vào
  `PairSignal` hay format — test `test_signal_format.py` có banned-words check.
- Schema change: chỉ additive (`CREATE/ALTER ... IF NOT EXISTS`), idempotent.

---

## 3. Smoke test trước commit

```powershell
py -3 .claude/skills/preflight/scripts/run_preflight.py        # dry
py -3 .claude/skills/preflight/scripts/run_preflight.py --live # LIVE-FIRE, cần ý định rõ
```

Dry = pytest + py_compile + diagnose scanner (read-only).
Live = chạy thật `py -3 main.py`: ghi bảng `signals`, có thể gửi Telegram.

---

## 4. Bot "im" — cây chẩn đoán

1. `py -3 scripts/diagnose_dexscreener.py`
   - các pair đều `no trigger` với số liệu thật → **quiet lành mạnh**, dừng ở đây.
   - `[MISS]`/`[ERROR]`/symbol mismatch → scanner/config hỏng → ingestion-scout.
2. `py -3 scripts/diagnose_outbox.py`
   - signal có nhưng `pending`/`failed` dồn → delivery hỏng → notifier-broadcaster.
   - `expired` > 0 trong 24h → cadence gap hoặc send fail kéo dài → cadence-check.
3. Skill `cadence-check` — coverage 2 ca so với cửa sổ 30 phút.
4. Skill `health-sweep` — fan-out 4 agent khi chưa khoanh được vùng.

> Lưu ý: confidence score KHÔNG liên quan đến bot "im". Score thấp không chặn
> gửi (doctrine "thà noise còn hơn miss"). Bot im = không pair vượt ngưỡng,
> chẩn đoán bằng các bước trên, KHÔNG phải bằng score.

Console Windows: prefix `PYTHONIOENCODING=utf-8` nếu script crash vì unicode.

---

## 5. KPI vận hành

| KPI | Nguồn | Ngưỡng |
|---|---|---|
| Send lag p95 | `diagnose_outbox.py` | ≤ 120s (SLA) |
| `expired` 24h | `diagnose_outbox.py` | = 0 |
| Coverage 24h | `cadence-check` | ≥ 95%, dead-air gap < 30 phút |
| Alert/ngày/pair | bảng `signals` | đủ thưa để mỗi alert đáng đọc — tune bằng signal-analyst |
| Phân bố confidence | `diagnose_scores.py` / `/score-audit` | spread, không dồn quanh 50 (lệch = cân lại `scoring.weights`) |

---

## 6. Sự cố thường gặp

| Triệu chứng | Nguyên nhân khả dĩ | Xử lý |
|---|---|---|
| 2 tin trùng nhau trên kênh | claim lease bị bỏ qua / code mới phá claim | kiểm tra `claim_tg_send_slot` còn được gọi trước MỌI send |
| Alert giá lệch xa chart | pair address sai hoặc pool đã cạn | re-validate bằng `validate_pair.py`, pin lại address |
| Spam cùng pair liên tục | cooldown quá ngắn / threshold quá thấp | signal-analyst tune per-pair override |
| GH Actions không chạy đêm | hết ca mà không tự dispatch (thiếu `WORKFLOW_PAT`) | dispatch tay 1 run, kiểm tra secret |
| Digest gửi 2 lần/ngày | `digest_state.json` bị xóa / chạy `--force` / 2 máy cùng chạy | kiểm tra marker; chỉ scheduler 1 nơi gọi `--live`; không dùng `--force` trừ khi cố ý |
| Mọi alert score ~50 | `scoring.weights` chưa phân biệt | `/score-audit` xem phân bố, cân lại weights (KHÔNG đụng thresholds) |
