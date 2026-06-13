"""
models/scoring.py
=================
Conviction Layer — chấm điểm tin cậy deterministic cho mỗi PairSignal.

KHÔNG LLM. KHÔNG sentiment. KHÔNG bullish/bearish. Đây là số học thuần trên
chính các số liệu DEXScreener đã có (biên độ, volume, áp lực mua/bán, đồng pha
đa khung, thanh khoản) — biểu diễn "nhiều chiều cùng đồng thuận" bằng một con
số 0–100 thay vì mô hình.

Hai sản phẩm:
  compute_confidence(...)      -> int 0..100   — độ tin cậy của move
  build_transmission_chain(...) -> str          — chuỗi bằng chứng nhân quả ngắn

Doctrine "thà noise còn hơn miss": điểm này KHÔNG BAO GIỜ chặn việc nổ/gửi alert.
Nó chỉ để hiển thị, lưu, và tăng cường routing premium. Mọi pair vượt ngưỡng vẫn
được gửi nguyên vẹn ra kênh chính.

Mọi hàm là pure (không I/O), guard chia-0, và deterministic: cùng input → cùng
output. Test phủ ở tests/unit/test_scoring.py.
"""

from __future__ import annotations

from typing import Dict, Mapping

from models.pair_signal import HORIZONS, HORIZON_LABEL

# Trọng số mặc định nếu config thiếu/lỗi — tổng nên = 1.0 nhưng code tự chuẩn hóa.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "magnitude": 0.25,   # vượt ngưỡng bao xa
    "volume": 0.25,      # volume trên gate bao nhiêu lần
    "pressure": 0.20,    # áp lực mua/bán đồng hướng với giá
    "alignment": 0.15,   # bao nhiêu khung cùng dấu với khung kích hoạt
    "liquidity": 0.15,   # thanh khoản dày = đáng tin hơn
}

# Hằng số chuẩn hóa sub-score về [0,1] — chọn để "đẹp ở mức vừa phải, bão hòa ở
# mức rất mạnh" thay vì tuyến tính vô hạn.
_MAGNITUDE_GATE_MULT = 3.0      # |%| = 3× ngưỡng → magnitude bão hòa
_VOLUME_GATE_MULT = 5.0         # volume = 5× gate → volume bão hòa
_LIQUIDITY_FULL_USD = 250_000.0  # ≥ mức này → liquidity sub-score = 1.0
_PRESSURE_MIN_TXNS = 10         # dưới mức này áp lực mua/bán vô nghĩa → sub = 0


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den else default


def _normalize_weights(raw: Mapping[str, float] | None) -> Dict[str, float]:
    """Lấy weights từ config, lấp khuyết bằng default, chuẩn hóa tổng = 1.0."""
    merged = {**DEFAULT_WEIGHTS}
    if raw:
        for key in DEFAULT_WEIGHTS:
            try:
                v = float(raw[key])  # type: ignore[index]
                if v >= 0:
                    merged[key] = v
            except (KeyError, TypeError, ValueError):
                continue
    total = sum(merged.values())
    if total <= 0:
        return {**DEFAULT_WEIGHTS}
    return {k: v / total for k, v in merged.items()}


def _magnitude_sub(change_pct: float, threshold_pct: float) -> float:
    """Vượt ngưỡng càng xa, điểm càng cao. Ngưỡng <=0 (không cấu hình) → 0.5 trung tính."""
    threshold = abs(threshold_pct)
    if threshold <= 0:
        return 0.5
    return _clamp01(abs(change_pct) / (threshold * _MAGNITUDE_GATE_MULT))


def _volume_sub(volume_usd: float, min_volume_gate: float) -> float:
    """Volume trên gate bao nhiêu lần. Gate <=0 → dùng mốc tham chiếu mềm."""
    gate = min_volume_gate if min_volume_gate and min_volume_gate > 0 else 1_000.0
    return _clamp01(_safe_div(volume_usd, gate * _VOLUME_GATE_MULT))


def _pressure_sub(direction: str, buys: int, sells: int) -> float:
    """
    Áp lực giao dịch ĐỒNG HƯỚNG với giá → tin cậy hơn.
    UP: tỷ lệ buys; DOWN: tỷ lệ sells. 0.5 (cân bằng) → 0 điểm; lệch hẳn → 1.
    Dưới ngưỡng mẫu tối thiểu → 0 (không có bằng chứng áp lực).
    """
    total = buys + sells
    if total < _PRESSURE_MIN_TXNS:
        return 0.0
    aligned = buys if direction == "UP" else sells
    fraction = _safe_div(aligned, total, 0.5)
    return _clamp01((fraction - 0.5) * 2.0)


def _alignment_sub(direction: str, changes: Mapping[str, float]) -> float:
    """Bao nhiêu khung có dữ liệu cùng dấu với hướng kích hoạt / tổng khung có dữ liệu."""
    available = [changes[h] for h in HORIZONS if h in changes]
    if not available:
        return 0.0
    want_positive = direction == "UP"
    aligned = sum(1 for c in available if (c > 0) == want_positive)
    return _clamp01(_safe_div(aligned, len(available)))


def _liquidity_sub(liquidity_usd: float) -> float:
    return _clamp01(_safe_div(liquidity_usd, _LIQUIDITY_FULL_USD))


def compute_confidence(
    *,
    change_pct: float,
    threshold_pct: float,
    volume_usd: float,
    min_volume_gate: float,
    liquidity_usd: float,
    buys: int,
    sells: int,
    changes: Mapping[str, float],
    direction: str,
    weights: Mapping[str, float] | None = None,
) -> int:
    """Blend 5 sub-score (mỗi cái 0..1) theo weights → điểm 0..100 (làm tròn int)."""
    w = _normalize_weights(weights)
    subs = {
        "magnitude": _magnitude_sub(change_pct, threshold_pct),
        "volume": _volume_sub(volume_usd, min_volume_gate),
        "pressure": _pressure_sub(direction, buys, sells),
        "alignment": _alignment_sub(direction, changes),
        "liquidity": _liquidity_sub(liquidity_usd),
    }
    score = sum(w[k] * subs[k] for k in subs)
    return max(0, min(100, round(score * 100)))


def build_transmission_chain(
    *,
    direction: str,
    volume_usd: float,
    min_volume_gate: float,
    buys: int,
    sells: int,
    changes: Mapping[str, float],
) -> str:
    """
    Chuỗi bằng chứng nhân quả ngắn, từ vựng TRUNG TÍNH (không từ cấm). Vd:
        "vol 3.2× gate · 71% buys · m5+h1+h6 aligned"
    Bỏ token áp lực khi thiếu mẫu; bỏ token vol khi không có gate hợp lệ.
    """
    parts: list[str] = []

    if min_volume_gate and min_volume_gate > 0:
        ratio = _safe_div(volume_usd, min_volume_gate)
        if ratio > 0:
            parts.append(f"vol {ratio:.1f}× gate")

    total = buys + sells
    if total >= _PRESSURE_MIN_TXNS:
        aligned = buys if direction == "UP" else sells
        pct = _safe_div(aligned, total) * 100
        label = "buys" if direction == "UP" else "sells"
        parts.append(f"{pct:.0f}% {label}")

    want_positive = direction == "UP"
    aligned_horizons = [
        HORIZON_LABEL[h] for h in HORIZONS
        if h in changes and (changes[h] > 0) == want_positive
    ]
    if len(aligned_horizons) >= 2:
        parts.append("+".join(aligned_horizons) + " aligned")

    return " · ".join(parts)
