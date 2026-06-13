"""Tests cho conviction layer (models/scoring.py): deterministic, bound 0..100,
guard chia-0, từ vựng trung tính (không từ cấm)."""

from models.scoring import (
    DEFAULT_WEIGHTS, build_transmission_chain, compute_confidence,
)

# Banned words contract — phải khớp tests/unit/test_signal_format.py
BANNED = ("bullish", "bearish", "sentiment", "ai-generated", "key takeaway", "breaking")


def _kw(**overrides):
    base = dict(
        change_pct=12.4,
        threshold_pct=4.0,
        volume_usd=850_000,
        min_volume_gate=10_000,
        liquidity_usd=2_400_000,
        buys=221,
        sells=109,
        changes={"m5": 1.1, "h1": 12.4, "h6": 8.0, "h24": 15.3},
        direction="UP",
    )
    base.update(overrides)
    return base


def test_confidence_in_bounds():
    assert 0 <= compute_confidence(**_kw()) <= 100


def test_confidence_deterministic():
    a = compute_confidence(**_kw())
    b = compute_confidence(**_kw())
    assert a == b


def test_stronger_move_scores_higher():
    weak = compute_confidence(**_kw(change_pct=4.1, volume_usd=11_000,
                                    buys=6, sells=5, changes={"h1": 4.1}))
    strong = compute_confidence(**_kw(change_pct=48.0, volume_usd=900_000,
                                      buys=400, sells=20))
    assert strong > weak


def test_zero_txns_no_crash_pressure_neutral():
    score = compute_confidence(**_kw(buys=0, sells=0))
    assert 0 <= score <= 100  # không chia 0


def test_zero_volume_gate_no_crash():
    assert 0 <= compute_confidence(**_kw(min_volume_gate=0, volume_usd=0)) <= 100


def test_zero_threshold_no_crash():
    assert 0 <= compute_confidence(**_kw(threshold_pct=0)) <= 100


def test_empty_changes_no_crash():
    assert 0 <= compute_confidence(**_kw(changes={})) <= 100


def test_zero_liquidity_no_crash():
    assert 0 <= compute_confidence(**_kw(liquidity_usd=0)) <= 100


def test_weights_missing_keys_falls_back_to_default():
    # weights rỗng -> dùng default; vẫn cho điểm hợp lệ
    s_default = compute_confidence(**_kw())
    s_empty = compute_confidence(**_kw(), weights={})
    assert s_default == s_empty


def test_weights_auto_normalized():
    # nhân đôi mọi trọng số = cùng tỉ lệ -> cùng điểm (vì chuẩn hóa tổng=1)
    doubled = {k: v * 2 for k, v in DEFAULT_WEIGHTS.items()}
    assert compute_confidence(**_kw()) == compute_confidence(**_kw(), weights=doubled)


def test_down_move_pressure_uses_sells():
    # DOWN với áp lực bán mạnh phải ăn điểm pressure cao hơn áp lực mua mạnh
    sell_heavy = compute_confidence(**_kw(direction="DOWN", change_pct=-12.4,
                                          buys=20, sells=300,
                                          changes={"h1": -12.4, "h6": -8.0}))
    buy_heavy = compute_confidence(**_kw(direction="DOWN", change_pct=-12.4,
                                         buys=300, sells=20,
                                         changes={"h1": -12.4, "h6": -8.0}))
    assert sell_heavy > buy_heavy


def test_transmission_chain_neutral_vocabulary():
    chain = build_transmission_chain(
        direction="UP", volume_usd=850_000, min_volume_gate=10_000,
        buys=221, sells=109, changes={"m5": 1.1, "h1": 12.4, "h6": 8.0},
    ).lower()
    for banned in BANNED:
        assert banned not in chain


def test_transmission_chain_content():
    chain = build_transmission_chain(
        direction="UP", volume_usd=850_000, min_volume_gate=10_000,
        buys=221, sells=109, changes={"m5": 1.1, "h1": 12.4, "h6": 8.0},
    )
    assert "vol" in chain and "× gate" in chain
    assert "67% buys" in chain          # 221/330
    assert "aligned" in chain           # m5+h1+h6 cùng dương


def test_transmission_chain_drops_pressure_when_few_txns():
    chain = build_transmission_chain(
        direction="UP", volume_usd=5_000, min_volume_gate=10_000,
        buys=2, sells=1, changes={"h1": 12.4},
    )
    assert "buys" not in chain          # <10 txn -> bỏ token áp lực


def test_transmission_chain_empty_when_no_evidence():
    # không gate hợp lệ, ít txn, 1 khung -> chuỗi rỗng, không crash
    chain = build_transmission_chain(
        direction="UP", volume_usd=0, min_volume_gate=0,
        buys=0, sells=0, changes={"h1": 5.0},
    )
    assert chain == ""
