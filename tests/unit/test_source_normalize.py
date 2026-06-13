from sources.normalize import normalize_dexscreener_pair, snapshot_key, symbol_matches


def _raw_pair():
    return {
        "chainId": "solana",
        "dexId": "raydium",
        "pairAddress": "PairAddress",
        "url": "https://dexscreener.com/solana/PairAddress",
        "baseToken": {"symbol": " WIF ", "address": "Mint"},
        "quoteToken": {"symbol": "SOL"},
        "priceUsd": "2.345",
        "liquidity": {"usd": "2400000"},
        "volume": {"m5": "1000", "h1": "850000"},
        "priceChange": {"m5": "1.1", "h1": "12.4"},
        "txns": {"h1": {"buys": "221", "sells": "109"}},
        "fdv": "2300000000",
        "marketCap": "2200000000",
    }


def test_normalize_dexscreener_pair_snapshot():
    snap = normalize_dexscreener_pair(_raw_pair())
    assert snap.source == "dexscreener_rest"
    assert snap.chain_id == "solana"
    assert snap.pair_address == "PairAddress"
    assert snap.base_symbol == "WIF"
    assert snap.quote_symbol == "SOL"
    assert snap.base_address == "Mint"
    assert snap.price_usd == 2.345
    assert snap.liquidity_usd == 2_400_000
    assert snap.volume["h1"] == 850_000
    assert snap.price_change["h1"] == 12.4
    assert snap.txns["h1"] == {"buys": 221, "sells": 109}


def test_symbol_matches_normalizes_config_and_api_symbols():
    assert symbol_matches(_raw_pair(), {"baseSymbol": "$WIF", "quoteSymbol": "SOL"})
    assert not symbol_matches(_raw_pair(), {"baseSymbol": "BONK", "quoteSymbol": "SOL"})


def test_snapshot_key_lowercases_identity():
    assert snapshot_key("Solana", "ABC") == "solana:abc"
