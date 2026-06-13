"""Provider payload normalization helpers."""

from __future__ import annotations

import math
from typing import Any

from sources.base import PairSnapshot, SOURCE_DEXSCREENER_REST


def num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def norm_symbol(raw: str | None) -> str:
    return str(raw or "").upper().strip().lstrip("$").strip()


def base_symbol(pair: dict) -> str:
    return str((pair.get("baseToken") or {}).get("symbol") or "").upper()


def quote_symbol(pair: dict) -> str:
    return str((pair.get("quoteToken") or {}).get("symbol") or "").upper()


def symbol_matches(pair: dict, entry: dict) -> bool:
    expected_base = norm_symbol(entry.get("baseSymbol"))
    expected_quote = norm_symbol(entry.get("quoteSymbol"))
    if expected_base and norm_symbol(base_symbol(pair)) != expected_base:
        return False
    if expected_quote and norm_symbol(quote_symbol(pair)) != expected_quote:
        return False
    return True


def snapshot_key(chain_id: str, pair_address: str) -> str:
    return f"{str(chain_id or '').lower()}:{str(pair_address or '').lower()}"


def normalize_dexscreener_pair(pair: dict) -> PairSnapshot:
    txns = {}
    for horizon, values in (pair.get("txns") or {}).items():
        values = values or {}
        txns[horizon] = {
            "buys": int(num(values.get("buys"))),
            "sells": int(num(values.get("sells"))),
        }

    return PairSnapshot(
        source=SOURCE_DEXSCREENER_REST,
        chain_id=str(pair.get("chainId") or ""),
        dex_id=str(pair.get("dexId") or ""),
        pair_address=str(pair.get("pairAddress") or ""),
        base_symbol=norm_symbol(base_symbol(pair)) or "TOKEN",
        quote_symbol=norm_symbol(quote_symbol(pair)) or "QUOTE",
        base_address=str((pair.get("baseToken") or {}).get("address") or "") or None,
        url=pair.get("url") or (
            f"https://dexscreener.com/{pair.get('chainId')}/{pair.get('pairAddress')}"
        ),
        price_usd=num(pair.get("priceUsd")),
        liquidity_usd=num((pair.get("liquidity") or {}).get("usd")),
        volume={k: num(v) for k, v in (pair.get("volume") or {}).items()},
        price_change={k: num(v) for k, v in (pair.get("priceChange") or {}).items()},
        txns=txns,
        fdv=num(pair.get("fdv")) or None,
        market_cap=num(pair.get("marketCap")) or None,
        raw=pair,
    )
