"""Tests cho PairSignal: format theo pattern kênh price-alert thị trường,
không tàn dư news/sentiment."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.pair_signal import (
    PairSignal, fmt_price, fmt_usd_compact, magnitude_emojis, pressure_bar,
)


def _signal(**overrides) -> PairSignal:
    base = dict(
        chain_id="solana",
        dex_id="raydium",
        pair_address="ExamplePair",
        base_symbol="WIF",
        quote_symbol="SOL",
        base_address="EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        url="https://dexscreener.com/solana/examplepair",
        horizon="h1",
        change_pct=12.4,
        price_usd=2.345,
        volume_usd=850_000,
        liquidity_usd=2_400_000,
        buys=221,
        sells=109,
        changes={"m5": 1.1, "h1": 12.4, "h6": 8.0, "h24": 15.3},
        fdv=2_300_000_000,
        market_cap=2_200_000_000,
        observed_at=datetime(2026, 6, 12, 16, 4, tzinfo=timezone.utc),
        dedup_key="dex:solana:ExamplePair:h1:UP:202606121600",
    )
    base.update(overrides)
    return PairSignal(**base)


def test_format_market_style_full_evidence():
    text = _signal().format_telegram_html()
    # Hook: emoji theo độ lớn + cashtag (12.4% -> 3 rocket, chưa hot -> không ⚡)
    assert text.startswith("🚀🚀🚀 <b>$WIF +12.4%</b> · 1h")
    assert "⚡" not in text
    # Thanh áp lực mua: 221/330 = 67% -> 5 xanh 3 đỏ
    assert "🟢🟢🟢🟢🟢🔴🔴🔴 67% buys (221/109)" in text
    assert "$2.35" in text and "WIF/SOL" in text
    assert "Raydium · Solana" in text
    assert "5m +1.1% | 1h +12.4% | 6h +8.0% | 24h +15.3%" in text
    assert "Vol $850.0K" in text and "Liq $2.4M" in text
    assert "MC $2.2B" in text and "FDV $2.3B" in text
    # Hàng hành động: Chart + Swap (solana -> jup.ag với mint thật)
    assert "dexscreener.com" in text
    assert "jup.ag/swap/SOL-EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm" in text
    # Hashtag lọc coin + giờ ICT (16:04 UTC -> 23:04 ICT)
    assert "#WIF #Solana" in text
    assert "23:04 ICT" in text


def test_format_has_zero_news_or_ai_remnants():
    text = _signal().format_telegram_html().lower()
    for banned in ("bullish", "bearish", "sentiment", "ai-generated", "key takeaway", "breaking"):
        assert banned not in text


def test_format_renders_conviction_line():
    text = _signal(
        confidence_score=87,
        transmission_chain="vol 3.2× gate · 71% buys · m5+h1 aligned",
    ).format_telegram_html()
    assert "🎯 <b>87</b>/100 · vol 3.2× gate · 71% buys · m5+h1 aligned" in text


def test_format_no_conviction_line_when_score_none():
    # Row DB cũ (NULL) hoặc scoring tắt -> không dòng conviction, không vỡ render.
    text = _signal().format_telegram_html()
    assert "🎯" not in text and "/100" not in text


def test_format_conviction_score_without_chain():
    text = _signal(confidence_score=40, transmission_chain="").format_telegram_html()
    assert "🎯 <b>40</b>/100" in text
    assert "/100 ·" not in text          # chuỗi rỗng -> không có ' · ' đuôi


def test_format_conviction_has_no_banned_words():
    text = _signal(
        confidence_score=92,
        transmission_chain="vol 5.0× gate · 80% sells · h1+h6+h24 aligned",
    ).format_telegram_html().lower()
    for banned in ("bullish", "bearish", "sentiment", "ai-generated", "key takeaway", "breaking"):
        assert banned not in text


def test_format_dump_uses_blood_and_hot_flag():
    text = _signal(change_pct=-9.3, dedup_key="dex:x:y:h1:DOWN:1").format_telegram_html()
    assert text.startswith("🩸🩸 <b>$WIF -9.3%</b> · 1h")
    hot = _signal(horizon="m5", change_pct=9.0).format_telegram_html()
    assert hot.startswith("🚀🚀 <b>$WIF +9.0%</b> · 5m ⚡")


def test_format_low_liquidity_warns_dyor():
    text = _signal(low_liquidity=True).format_telegram_html()
    assert "Low liquidity — DYOR" in text


def test_format_minimal_data_still_renders():
    text = _signal(
        changes={}, market_cap=None, fdv=None, base_address=None, buys=2, sells=1
    ).format_telegram_html()
    assert "$WIF +12.4%" in text
    assert "⏳" not in text and "MC" not in text
    assert "Swap" not in text          # không base_address -> không link Swap
    assert "🟢 2 buys · 🔴 1 sells" in text  # ít txn -> không bar, rơi về số thô


def test_format_cleans_dirty_symbols_from_old_rows():
    text = _signal(base_symbol=" $FARTCOIN ", quote_symbol=" SOL ").format_telegram_html()
    assert "$FARTCOIN" in text
    assert "FARTCOIN/SOL" in text
    assert "#FARTCOIN #Solana" in text
    assert "FARTCOIN /SOL" not in text
    assert "#FARTCOIN  #Solana" not in text


def test_swap_url_only_for_mapped_chains():
    assert "jup.ag" in _signal().swap_url
    eth = _signal(chain_id="ethereum", base_address="0xabc")
    assert "app.uniswap.org" in eth.swap_url and "0xabc" in eth.swap_url
    assert _signal(chain_id="base").swap_url is None
    assert _signal(base_address=None).swap_url is None


def test_magnitude_emojis_tiers():
    assert magnitude_emojis(1.0) == "🚀"
    assert magnitude_emojis(5.0) == "🚀🚀"
    assert magnitude_emojis(12.4) == "🚀🚀🚀"
    assert magnitude_emojis(-25.0) == "🩸🩸🩸🩸"
    assert magnitude_emojis(60.0) == "🚀🚀🚀🚀🚀"


def test_pressure_bar_rules():
    assert pressure_bar(2, 1) is None                      # thiếu mẫu
    assert pressure_bar(10, 0) == "🟢🟢🟢🟢🟢🟢🟢🟢 100% buys (10/0)"
    mixed = pressure_bar(1, 99)
    assert mixed.startswith("🟢") and "🔴" in mixed        # có mua thì bar không tuyệt đối đỏ


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
