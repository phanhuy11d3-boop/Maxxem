"""Tests cho render leaderboard digest (utils.notifier.render_digest_html) — pure,
không gửi mạng. Đảm bảo xếp hạng hiển thị đúng và không từ cấm."""

from utils.notifier import render_digest_html

BANNED = ("bullish", "bearish", "sentiment", "ai-generated", "key takeaway", "breaking")


def _mover(symbol, change, score=None, **extra):
    base = dict(
        base_symbol=symbol, quote_symbol="SOL", chain_id="solana",
        change_pct=change, horizon="h1", price_usd=2.34,
        volume_usd=850_000, confidence_score=score,
    )
    base.update(extra)
    return base


def test_digest_lists_movers_in_order():
    movers = [_mover("WIF", 24.1, 82), _mover("BONK", -11.0, 60)]
    text = render_digest_html(movers, window_label="24h", ict_label="2026-06-13 ICT")
    assert "Top Movers 24h" in text
    assert "1. " in text and "$WIF +24.1%" in text
    assert "2. " in text and "$BONK -11.0%" in text
    assert "🎯 82" in text and "🎯 60" in text
    assert "Vol $850.0K" in text


def test_digest_empty_state():
    text = render_digest_html([], window_label="24h")
    assert "Không pair nào vượt ngưỡng" in text


def test_digest_handles_missing_score():
    text = render_digest_html([_mover("PEPE", 9.0, None)])
    assert "$PEPE +9.0%" in text
    assert "🎯" not in text  # không có điểm -> không hiện huy hiệu


def test_digest_no_banned_words():
    movers = [_mover("WIF", 24.1, 82), _mover("DOGE", -15.0, 70)]
    text = render_digest_html(movers).lower()
    for banned in BANNED:
        assert banned not in text
