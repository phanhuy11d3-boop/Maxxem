from datetime import datetime, timezone

from scrapers.dexscreener import load_config
from models.article import Article, MarketImpact
from scrapers.dexscreener import build_alert_article


def _pair(change: float = 12.4):
    return {
        "chainId": "solana",
        "dexId": "raydium",
        "url": "https://dexscreener.com/solana/examplepair",
        "pairAddress": "examplepair",
        "baseToken": {"symbol": "WIF"},
        "quoteToken": {"symbol": "SOL"},
        "priceUsd": "2.345",
        "txns": {"h1": {"buys": 221, "sells": 109}},
        "volume": {"h1": 850000},
        "priceChange": {"h1": change},
        "liquidity": {"usd": 2400000},
        "fdv": 2300000000,
        "marketCap": 2200000000,
    }


def test_dexscreener_alert_is_actionable_price_move():
    now = datetime(2026, 6, 11, 10, 7, tzinfo=timezone.utc)
    article = build_alert_article(
        _pair(12.4),
        "h1",
        12.4,
        {"cooldown_minutes": 15},
        now=now,
    )

    assert article.source == "DEXScreener"
    assert article.processed is True
    assert article.is_actionable is True
    assert article.market_impact == MarketImpact.BULLISH
    assert article.affected_tokens == ["$WIF"]
    assert "WIF/SOL UP +12.4% in h1" in article.title
    assert "vol $850.0K" in article.key_takeaway
    assert "liq $2.4M" in article.key_takeaway
    assert "221B/109S" in article.key_takeaway
    assert article.dedup_key == "dex:solana:examplepair:h1:UP:202606111000"


def test_dedup_key_allows_repeated_events_on_same_url():
    base = Article(
        url="https://dexscreener.com/solana/examplepair",
        dedup_key="dex:solana:examplepair:h1:UP:202606111000",
        title="WIF/SOL UP",
        source="DEXScreener",
        published_at=datetime.now(timezone.utc),
    )
    later = base.model_copy(update={"dedup_key": "dex:solana:examplepair:h1:UP:202606111015"})

    assert base.id != later.id
    assert str(base.url) == str(later.url)


def test_dexscreener_watchlist_is_pinned_against_wrong_pair_resolution():
    cfg = load_config()
    assert cfg["enabled"] is True
    assert cfg["watchlist"], "DEXScreener watchlist must not be empty"

    for entry in cfg["watchlist"]:
        assert entry.get("pairAddress"), f"{entry.get('name')} must pin pairAddress"
        assert entry.get("chainId"), f"{entry.get('name')} must pin chainId"
        assert entry.get("baseSymbol"), f"{entry.get('name')} must declare baseSymbol"
        assert entry.get("quoteSymbol"), f"{entry.get('name')} must declare quoteSymbol"
