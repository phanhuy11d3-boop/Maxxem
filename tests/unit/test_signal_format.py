"""Tests cho PairSignal: format Telegram bảng giá, không tàn dư news/sentiment."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.signal import PairSignal, fmt_price, fmt_usd_compact


def _signal(**overrides) -> PairSignal:
    base = dict(
        chain_id="solana",
        dex_id="raydium",
        pair_address="ExamplePair",
        base_symbol="WIF",
        quote_symbol="SOL",
        url="https://dexscreener.com/solana/examplepair",
        horizon="h1",
        change_pct=12.4,
        price_usd=2.345,
        volume_usd=850_000,
        liquidity_usd=2_400_000,
        buys=221,
        sells=109,
        changes={"m5": 1.1, "h1": 12.4, "h6": 8.0, "h24": 15.3},
        market_cap=2_200_000_000,
        observed_at=datetime(2026, 6, 12, 16, 4, tzinfo=timezone.utc),
        dedup_key="dex:solana:ExamplePair:h1:UP:202606121600",
    )
    base.update(overrides)
    return PairSignal(**base)


def test_format_is_price_board_with_full_evidence():
    text = _signal().format_telegram_html()
    assert text.startswith("🚀 <b>WIF/SOL +12.4%</b> · 1h")
    assert "$2.35" in text                      # giá (làm tròn 2 thập phân)
    assert "Raydium · Solana" in text           # venue
    assert "5m +1.1% | 1h +12.4% | 6h +8.0% | 24h +15.3%" in text  # đa khung
    assert "Vol 1h $850.0K" in text
    assert "Liq $2.4M" in text
    assert "221 buys" in text and "109 sells" in text
    assert "MC $2.2B" in text
    assert "dexscreener.com" in text
    assert "23:04 ICT" in text                  # 16:04 UTC -> ICT (+7)


def test_format_has_zero_news_or_ai_remnants():
    text = _signal().format_telegram_html().lower()
    for banned in ("bullish", "bearish", "sentiment", "ai-generated", "key takeaway", "breaking"):
        assert banned not in text


def test_format_dump_uses_blood_arrow():
    text = _signal(change_pct=-9.3, dedup_key="dex:x:y:h1:DOWN:1").format_telegram_html()
    assert text.startswith("🩸 <b>WIF/SOL -9.3%</b> · 1h")


def test_format_low_liquidity_warns_dyor():
    text = _signal(low_liquidity=True).format_telegram_html()
    assert "Low liquidity — DYOR" in text


def test_format_minimal_data_still_renders():
    text = _signal(changes={}, market_cap=None, fdv=None).format_telegram_html()
    assert "WIF/SOL +12.4%" in text
    assert "⏳" not in text and "MC" not in text


def test_direction_and_hot():
    assert _signal().direction == "UP"
    assert _signal(change_pct=-1.0).direction == "DOWN"
    assert _signal(horizon="m5", change_pct=9.0).is_hot is True
    assert _signal(horizon="h24", change_pct=16.0).is_hot is True
    assert _signal(horizon="h1", change_pct=5.0).is_hot is False


def test_id_derives_from_dedup_key():
    a = _signal()
    b = _signal(price_usd=9.99)  # khác số liệu nhưng cùng dedup_key
    assert a.id == b.id
    c = _signal(dedup_key="dex:solana:ExamplePair:h1:UP:202606121615")
    assert a.id != c.id


def test_invalid_horizon_rejected():
    with pytest.raises(ValidationError):
        _signal(horizon="h12")


def test_usd_formatting():
    assert fmt_usd_compact(2_200_000_000) == "$2.2B"
    assert fmt_usd_compact(850_000) == "$850.0K"
    assert fmt_usd_compact(850_0) == "$8.5K"
    assert fmt_price(0.00001234) == "$0.00001234"
    assert fmt_price(1234.4) == "$1,234"
