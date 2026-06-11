"""DEXScreener price-movement scanner.

Produces deterministic, already-actionable Article objects for direct pair
movement alerts: price change, liquidity, volume, buys/sells and DEX link.
No LLM is required for this path.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

from models.article import Article, MarketImpact

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dexscreener.yaml"
HORIZONS = ("m5", "h1", "h6", "h24")
HTTP_TIMEOUT_S = 10


def load_config(path: str | Path = CONFIG_PATH) -> dict:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("enabled", True)
        data.setdefault("cooldown_minutes", 15)
        data.setdefault("min_liquidity_usd", 50000)
        data.setdefault("min_volume_usd", {})
        data.setdefault("thresholds_pct", {})
        data.setdefault("watchlist", [])
        return data
    except FileNotFoundError:
        logger.warning("DEXScreener config not found: %s", path)
        return {"enabled": False, "watchlist": []}
    except yaml.YAMLError as exc:
        logger.warning("DEXScreener config parse error: %s", exc)
        return {"enabled": False, "watchlist": []}


def _get_json(path: str, params: Optional[dict] = None) -> Any:
    resp = requests.get(f"{BASE_URL}{path}", params=params or {}, timeout=HTTP_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _fmt_usd(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    if value >= 1:
        return f"${value:.2f}"
    return f"${value:.6f}"


def _fmt_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _base_symbol(pair: dict) -> str:
    return str((pair.get("baseToken") or {}).get("symbol") or "").upper()


def _quote_symbol(pair: dict) -> str:
    return str((pair.get("quoteToken") or {}).get("symbol") or "").upper()


def _pair_label(pair: dict) -> str:
    base = _base_symbol(pair) or "TOKEN"
    quote = _quote_symbol(pair) or "QUOTE"
    return f"{base}/{quote}"


def _symbol_matches(pair: dict, entry: dict) -> bool:
    expected_base = str(entry.get("baseSymbol") or "").upper().strip()
    expected_quote = str(entry.get("quoteSymbol") or "").upper().strip()
    if expected_base and _base_symbol(pair) != expected_base:
        return False
    if expected_quote and _quote_symbol(pair) != expected_quote:
        return False
    return True


def _best_pair(candidates: list[dict], entry: dict) -> Optional[dict]:
    chain_id = entry.get("chainId")
    if chain_id:
        candidates = [p for p in candidates if str(p.get("chainId", "")).lower() == chain_id.lower()]
    candidates = [p for p in candidates if _symbol_matches(p, entry)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: _num((p.get("liquidity") or {}).get("usd")))


def fetch_pair(entry: dict) -> Optional[dict]:
    chain_id = entry.get("chainId")
    pair_address = entry.get("pairAddress")
    if chain_id and pair_address:
        data = _get_json(f"/latest/dex/pairs/{chain_id}/{pair_address}")
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        pair = pairs[0]
        return pair if _symbol_matches(pair, entry) else None

    query = entry.get("query") or entry.get("name")
    if not query:
        return None
    data = _get_json("/latest/dex/search", {"q": query})
    return _best_pair(data.get("pairs") or [], entry)


def _trigger(pair: dict, cfg: dict) -> Optional[tuple[str, float]]:
    liquidity = _num((pair.get("liquidity") or {}).get("usd"))
    if liquidity < _num(cfg.get("min_liquidity_usd"), 0):
        return None

    thresholds = cfg.get("thresholds_pct") or {}
    min_volume = cfg.get("min_volume_usd") or {}
    price_change = pair.get("priceChange") or {}
    volume = pair.get("volume") or {}

    hits: list[tuple[str, float]] = []
    for horizon in HORIZONS:
        change = _num(price_change.get(horizon))
        threshold = _num(thresholds.get(horizon), 0)
        if threshold <= 0 or abs(change) < threshold:
            continue
        if _num(volume.get(horizon)) < _num(min_volume.get(horizon), 0):
            continue
        hits.append((horizon, change))
    if not hits:
        return None
    return max(hits, key=lambda item: abs(item[1]))


def _bucket(now: datetime, cooldown_minutes: int) -> str:
    cooldown = max(1, int(cooldown_minutes))
    minute = (now.minute // cooldown) * cooldown
    return now.replace(minute=minute, second=0, microsecond=0).strftime("%Y%m%d%H%M")


def build_alert_article(pair: dict, horizon: str, change_pct: float, cfg: dict, now: Optional[datetime] = None) -> Article:
    now = now or datetime.now(timezone.utc)
    label = _pair_label(pair)
    base = _base_symbol(pair) or "TOKEN"
    quote = _quote_symbol(pair) or "QUOTE"
    price_usd = _num(pair.get("priceUsd"))
    liquidity = _num((pair.get("liquidity") or {}).get("usd"))
    volume = _num((pair.get("volume") or {}).get(horizon))
    txns = (pair.get("txns") or {}).get(horizon) or {}
    buys = int(_num(txns.get("buys")))
    sells = int(_num(txns.get("sells")))
    direction = "UP" if change_pct > 0 else "DOWN"
    impact = MarketImpact.BULLISH if change_pct > 0 else MarketImpact.BEARISH
    abs_change = abs(change_pct)
    urgency = "breaking" if horizon == "m5" and abs_change >= 8 else "important"
    url = pair.get("url") or f"https://dexscreener.com/{pair.get('chainId')}/{pair.get('pairAddress')}"
    bucket = _bucket(now, int(cfg.get("cooldown_minutes", 15)))
    dedup_key = f"dex:{pair.get('chainId')}:{pair.get('pairAddress')}:{horizon}:{direction}:{bucket}"

    title = f"{label} {direction} {_fmt_pct(change_pct)} in {horizon} | price {_fmt_usd(price_usd)}"
    key = (
        f"{label} {_fmt_pct(change_pct)} {horizon}; vol {_fmt_usd(volume)}, "
        f"liq {_fmt_usd(liquidity)}, txns {buys}B/{sells}S."
    )
    summary = (
        f"DEXScreener pair move on {pair.get('chainId')}/{pair.get('dexId')}: "
        f"priceUsd={price_usd}, priceChange.{horizon}={change_pct}, "
        f"volume.{horizon}={volume}, liquidity.usd={liquidity}, buys={buys}, sells={sells}, "
        f"fdv={pair.get('fdv')}, marketCap={pair.get('marketCap')}."
    )

    return Article(
        url=url,
        dedup_key=dedup_key,
        title=title,
        source="DEXScreener",
        published_at=now,
        summary=summary,
        # Không có sentiment: đây là số liệu giá trực tiếp, không phải suy đoán.
        market_impact=impact,
        key_takeaway=key[:300],
        narrative_tag="DEX_MOVE",
        affected_tokens=[f"${base}"],
        urgency=urgency,
        low_confidence=liquidity < 100_000,
        published_from_source=True,
        processed=True,
    )


def fetch_dexscreener_alerts(config_path: str | Path = CONFIG_PATH) -> list[Article]:
    cfg = load_config(config_path)
    if not cfg.get("enabled", True):
        return []

    alerts: list[Article] = []
    for entry in cfg.get("watchlist") or []:
        try:
            pair = fetch_pair(entry)
            if not pair:
                logger.warning("DEXScreener no pair for %s", entry)
                continue
            hit = _trigger(pair, cfg)
            if not hit:
                continue
            horizon, change = hit
            alerts.append(build_alert_article(pair, horizon, change, cfg))
        except Exception as exc:
            logger.warning("DEXScreener fetch skipped for %s: %s", entry.get("name") or entry, exc)
    logger.info("DEXScreener alerts: %s", len(alerts))
    return alerts


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for article in fetch_dexscreener_alerts():
        print(article.title)
