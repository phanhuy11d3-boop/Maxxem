# Guardrails — ràng buộc vận hành & nội dung (v3 DEX-only)

Enforce qua `CLAUDE.md`, logic scanner trong
[`scrapers/dexscreener.py`](../scrapers/dexscreener.py), format trong
[`models/pair_signal.py`](../models/pair_signal.py), conviction layer trong
[`models/scoring.py`](../models/scoring.py), và tests
`tests/unit/test_signal_format.py` + `test_scoring.py`.

---

## 1. Không hallucination số liệu

- Mọi con số trong alert (giá, %, volume, liquidity, txns, MC) đến trực tiếp
  từ DEXScreener API response. Không có bước nào "diễn giải" hay ước lượng.
- Không có LLM trong pipeline — đây là guardrail mạnh nhất: thứ không tồn tại
  không thể bịa.

## 2. Không opinion, không hype

- Không nhãn bullish/bearish, không sentiment, không "to the moon".
- Hướng đi = dấu của `change_pct`, hiển thị bằng 🚀/🩸 và con số có dấu.
- Test enforce banned words: `bullish`, `bearish`, `sentiment`,
  `ai-generated`, `key takeaway`, `breaking`.
- `confidence_score` là SỐ HỌC deterministic, KHÔNG phải opinion: nó đo độ
  mạnh/đồng thuận của chính các số liệu, không suy đoán hướng tương lai.
  `transmission_chain` chỉ dùng từ vựng trung tính (`vol`, `gate`, `buys`,
  `sells`, `aligned`) và cũng chịu test từ-cấm (`test_scoring.py`).

## 2b. Score không bao giờ chặn alert (doctrine "thà noise còn hơn miss")

- `confidence_score` CHỈ để hiển thị + lưu DB + augment routing premium.
- KHÔNG nằm trong `_trigger`: mọi pair vượt ngưỡng vẫn gửi ra kênh chính bất
  kể điểm cao hay thấp. Test `test_score_does_not_affect_trigger` khóa điều này.
- Tinh chỉnh điểm = sửa `scoring.weights` (config), KHÔNG đụng `thresholds_pct`.

## 3. Chống nhầm token (wrong-pair = mất niềm tin nặng nhất)

- Production watchlist phải pin `chainId` + `pairAddress` + `baseSymbol` +
  `quoteSymbol`.
- Scanner so symbol API trả về với config — mismatch thì SKIP + log error,
  không bao giờ gửi.
- Pair mới phải qua `validate_pair.py` (skill `add-source`) trước khi vào config.

## 4. Chống alert rác

- Liquidity gate (`min_liquidity_usd`) chặn pool mỏng bị thao túng.
- Volume gate per-horizon chặn move % to trên volume không đáng kể.
- Liquidity < $100k vẫn vượt gate → alert gắn `⚠️ Low liquidity — DYOR`.
- Cooldown bucket trong dedup_key chặn spam cùng move; đảo chiều được phép
  alert ngay (dedup_key chứa direction).

## 5. Chống giá nguội

- Alert quá 30 phút kể từ `observed_at` → `expired`, không gửi.
- SLA observed→sent 120s; vi phạm thì warning log + admin alert.

## 6. An toàn vận hành

- `py -3 main.py` là LIVE-FIRE (ghi DB + gửi Telegram) — không chạy "thử".
- `py -3 scripts/daily_digest.py --live` là LIVE-FIRE (gửi Telegram). Bản
  không `--live` chỉ in ra, an toàn. Digest idempotent 1 tin/ngày UTC.
- Heartbeat/admin không bao giờ vào `CHAT_ID`.
- Subagent read-only bị hook `guard_readonly` chặn SQL write + live-fire.
- Secret không xuất hiện trong code/docs/tests/log — kể cả dạng ví dụ.

## 7. Schema additive

- Cột mới (`confidence_score`, `transmission_chain`) thêm bằng `ALTER TABLE …
  ADD COLUMN IF NOT EXISTS`; `init_db()` giữ idempotent. Không DROP/đổi cột
  sống khi chưa có lệnh operator. Row cũ NULL được đọc NULL-safe, render bỏ qua.
