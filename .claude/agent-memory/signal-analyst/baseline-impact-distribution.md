---
name: baseline-impact-distribution
description: Baseline market_impact distribution & triage rates as of 2026-06-10 audit — reference point for detecting neutral-drift
metadata:
  type: project
---

Baseline số liệu chất lượng signal, audit read-only ngày 2026-06-10.

**Lifetime (theo db-auditor cùng ngày):** 1527 processed = 932 neutral (61%) / 312 bullish / 283 bearish. Triage 8B đã loại tổng cộng 220. 70B output: 712 neutral + 595 actionable (~45% actionable trên bài được 70B phân tích).

**Từ code mới (>= 2026-05-06 04:00 UTC):** 1320 processed = 788 neutral (59.7%) / 273 bullish / 259 bearish; 5161 bài `<unproc>` tích lũy (stale-30min nên backlog không bao giờ được xử lý — by design).

**24h gần nhất (2026-06-10):** 30 processed = 9 neutral / 21 actionable (70% actionable — KHÔNG có neutral-drift); triage 8B loại 0; 203 unprocessed (upstream cadence GH Actions đứng, đã biết từ db-auditor — không phải lỗi prompt).

**Direct 70B sample (5 bài):** 2/5 actionable, lý do hợp lý cho 3 neutral.

**Quirks calibration cần theo dõi (chưa phải bug):**
- Bài bearish nhưng sentiment=0.0 (Chainalysis $36.7M) — dấu hiệu sign-mismatch nhẹ.
- Bài borderline flip giữa các lần chạy dù temperature=0.0 (Humanity bug bounty: neutral 0.0 trong production vs bearish -0.5 khi gọi trực tiếp) — nondeterminism phía provider.
- Bài macro actionable (CPI, KOSPI, CME futures) thường có `affected_tokens=[]` — token mapping bỏ trống cho macro.

**Why:** cần mốc so sánh cố định để phát hiện drift "neutralize everything" ở các audit sau.
**How to apply:** nếu tỷ lệ neutral trên bài 70B xử lý vượt xa ~55-65%, hoặc triage 8B loại > ~20% batch Tier-2, so với baseline này thì điều tra prompt drift. Liên quan [[env-quirks-diagnostics]].
