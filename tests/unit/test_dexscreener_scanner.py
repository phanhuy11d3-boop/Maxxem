"""Tests cho scanner DEXScreener: trigger gates, cooldown bucket, build_signal."""

from datetime import datetime, timezone

from scrapers.dexscreener import (
    _bucket, _entry_cfg, _symbol_matches, _trigger, build_signal,
)


def _pair(change_h1: float = 12.4, liquidity: float = 2_400_000, volume_h1: float = 850_000):
    return {
        "chainId": "solana",
        "dexId": "raydium",
        "url": "https://dexscreener.com/solana/examplepair",
        "pairAddress": "ExamplePair",
        "baseToken": {"symbol": "WIF"},
        "quoteToken": {"symbol": "SOL"},
        "priceUsd": "2.345",
        "txns": {"h1": {"buys": 221, "sells": 109}},
        "volume": {"h1": volume_h1, "m5": 1000},
        "priceChange": {"m5": 1.1, "h1": change_h1, "h6": 8.0, "h24": 15.3},
        "liquidity": {"usd": liquidity},
        "fdv": 2_300_000_000,
        "marketCap": 2_200_000_000,
    }


CFG = {
    "cooldown_minutes": 15,
    "min_liquidity_usd": 50_000,
    "min_volume_usd": {"h1": 10_000},
    "thresholds_pct": {"m5": 2.0, "h1": 4.0, "h6": 8.0, "h24": 12.0},
}


def test_trigger_picks_strongest_horizon():
    horizon, change = _trigger(_pair(), CFG)
    # h24 +15.3% mạnh hơn h1 +12.4% và h6 +8.0%
    assert horizon == "h24"
    assert change == 15.3


def test_trigger_blocked_by_liquidity_gate():
    assert _trigger(_pair(liquidity=10_000), CFG) is None


def test_trigger_blocked_by_volume_gate():
    cfg = {**CFG, "thresholds_pct": {"h1": 4.0}, "min_volume_usd": {"h1": 10_000_000}}
    assert _trigger(_pair(), cfg) is None


def test_trigger_none_when_below_threshold():
    cfg = {**CFG, "thresholds_pct": {"h1": 50.0}}
    assert _trigger(_pair(change_h1=3.0), cfg) is None


def test_trigger_negative_move_fires():
    cfg = {**CFG, "thresholds_pct": {"h1": 4.0}}
    horizon, change = _trigger(_pair(change_h1=-9.9), cfg)
    assert horizon == "h1"
    assert change == -9.9


def test_bucket_stable_within_cooldown_window():
    a = _bucket(datetime(2026, 6, 12, 10, 1, tzinfo=timezone.utc), 15)
    b = _bucket(datetime(2026, 6, 12, 10, 14, tzinfo=timezone.utc), 15)
    c = _bucket(datetime(2026, 6, 12, 10, 16, tzinfo=timezone.utc), 15)
    assert a == b
    assert a != c


def test_build_signal_structured_fields_and_dedup():
    now = datetime(2026, 6, 12, 10, 7, tzinfo=timezone.utc)
    sig = build_signal(_pair(), "h1", 12.4, CFG, now=now)

    assert sig.pair_label == "WIF/SOL"
    assert sig.direction == "UP"
    assert sig.change_pct == 12.4
    assert sig.price_usd == 2.345
    assert sig.volume_usd == 850_000
    assert sig.liquidity_usd == 2_400_000
    assert sig.buys == 221 and sig.sells == 109
    assert sig.changes == {"m5": 1.1, "h1": 12.4, "h6": 8.0, "h24": 15.3}
    assert sig.low_liquidity is False
    # Cooldown bucket 10:07 với cooldown 15' -> 10:00
    assert sig.dedup_key == "dex:solana:ExamplePair:h1:UP:202606121000"
    # Cùng bucket -> cùng id (DB ON CONFLICT chặn spam)
    again = build_signal(_pair(), "h1", 12.4, CFG, now=datetime(2026, 6, 12, 10, 14, tzinfo=timezone.utc))
    assert sig.id == again.id


def test_build_signal_down_move_separate_dedup():
    now = datetime(2026, 6, 12, 10, 7, tzinfo=timezone.utc)
    up = build_signal(_pair(12.4), "h1", 12.4, CFG, now=now)
    down = build_signal(_pair(-12.4), "h1", -12.4, CFG, now=now)
    assert down.direction == "DOWN"
    assert up.id != down.id  # đảo chiều trong cùng bucket vẫn alert được


def test_build_signal_flags_low_liquidity():
    sig = build_signal(_pair(liquidity=60_000), "h1", 12.4, CFG)
    assert sig.low_liquidity is True


def test_symbol_mismatch_guard():
    entry = {"baseSymbol": "WIF", "quoteSymbol": "SOL"}
    assert _symbol_matches(_pair(), entry) is True
    wrong = {"baseSymbol": "BONK", "quoteSymbol": "SOL"}
    assert _symbol_matches(_pair(), wrong) is False
    # tiền tố $ trong config không làm fail so khớp
    dollar = {"baseSymbol": "$WIF", "quoteSymbol": "SOL"}
    assert _symbol_matches(_pair(), dollar) is True


def test_entry_cfg_per_pair_override():
    entry = {"thresholds_pct": {"h1": 99.0}, "min_liquidity_usd": 1}
    eff = _entry_cfg(entry, CFG)
    assert eff["thresholds_pct"]["h1"] == 99.0
    assert eff["thresholds_pct"]["h24"] == 12.0  # global giữ nguyên
    assert eff["min_liquidity_usd"] == 1
    assert _trigger(_pair(), eff)[0] == "h24"  # h1 bị override 99% nên h24 thắng
