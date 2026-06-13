from datetime import datetime, timezone

from models.pair_signal import PairSignal
from utils.alert_priority import sort_by_priority


def _signal(symbol: str, change: float, score=None, horizon="h1"):
    return PairSignal(
        chain_id="solana",
        dex_id="raydium",
        pair_address=symbol,
        base_symbol=symbol,
        quote_symbol="SOL",
        url=f"https://dexscreener.com/solana/{symbol}",
        horizon=horizon,
        change_pct=change,
        price_usd=1,
        volume_usd=1000,
        liquidity_usd=100_000,
        buys=10,
        sells=5,
        changes={horizon: change},
        observed_at=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        dedup_key=f"dex:solana:{symbol}:{horizon}:UP:1",
        confidence_score=score,
    )


def test_sort_by_priority_hot_then_score_then_abs_change():
    low = _signal("LOW", 3, score=90)
    hot = _signal("HOT", 16, score=10)
    scored = _signal("SCORED", 5, score=80)
    bigger = _signal("BIGGER", 8, score=80)

    ordered = sort_by_priority([low, scored, hot, bigger])
    assert [s.base_symbol for s in ordered] == ["HOT", "LOW", "BIGGER", "SCORED"]
