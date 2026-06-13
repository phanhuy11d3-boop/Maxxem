from datetime import datetime, timezone

from signals.engine import build_signal_from_snapshot, entry_config, evaluate_snapshot
from sources.normalize import normalize_dexscreener_pair


def _snapshot(change_h1=12.4, liquidity=2_400_000, volume_h1=850_000):
    pair = {
        "chainId": "solana",
        "dexId": "raydium",
        "pairAddress": "ExamplePair",
        "baseToken": {"symbol": "WIF", "address": "Mint"},
        "quoteToken": {"symbol": "SOL"},
        "url": "https://dexscreener.com/solana/ExamplePair",
        "priceUsd": "2.345",
        "liquidity": {"usd": liquidity},
        "volume": {"m5": 1000, "h1": volume_h1, "h6": 20_000, "h24": 50_000},
        "priceChange": {"m5": 1.1, "h1": change_h1, "h6": 8.0, "h24": 15.3},
        "txns": {"h1": {"buys": 221, "sells": 109}, "h24": {"buys": 400, "sells": 200}},
        "marketCap": 2_200_000_000,
    }
    return normalize_dexscreener_pair(pair)


CFG = {
    "cooldown_minutes": 15,
    "min_liquidity_usd": 50_000,
    "min_volume_usd": {"h1": 10_000, "h24": 10_000},
    "thresholds_pct": {"h1": 4.0, "h24": 12.0},
}


def test_evaluate_snapshot_picks_strongest_horizon():
    decision = evaluate_snapshot(_snapshot(), CFG)
    assert decision.horizon == "h24"
    assert decision.change_pct == 15.3


def test_evaluate_snapshot_blocks_low_liquidity():
    assert evaluate_snapshot(_snapshot(liquidity=10_000), CFG) is None


def test_entry_config_merges_pair_override():
    eff = entry_config({"thresholds_pct": {"h1": 99.0}}, CFG)
    assert eff["thresholds_pct"]["h1"] == 99.0
    assert eff["thresholds_pct"]["h24"] == 12.0


def test_build_signal_from_snapshot_keeps_dedup_contract():
    now = datetime(2026, 6, 12, 10, 7, tzinfo=timezone.utc)
    decision = evaluate_snapshot(_snapshot(), {"**": "unused", **CFG})
    sig = build_signal_from_snapshot(_snapshot(), decision, CFG, now=now)
    assert sig.pair_label == "WIF/SOL"
    assert sig.dedup_key == "dex:solana:ExamplePair:h24:UP:202606120000"
    assert sig.base_address == "Mint"
    assert sig.confidence_score is not None

