"""DEXScreener price-movement scanner — sản phẩm lõi của CryptoSentinel.

Quét watchlist pair đã pin (chainId + pairAddress), so với ngưỡng %/volume/
liquidity, và emit PairSignal hoàn toàn deterministic. Không LLM, không news.

Tối ưu: pair pin được fetch BATCH theo chain (API cho phép tới 30 address
mỗi request) — watchlist 8 pair trên 2 chain = 2 HTTP call thay vì 8.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

from models.pair_signal import HORIZONS, PairSignal

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dexscreener.yaml"
HTTP_TIMEOUT_S = 10
BATCH_MAX_ADDRESSES = 30  # giới hạn API /latest/dex/pairs

# Dưới mức này alert vẫn gửi (nếu qua min_liquidity_usd) nhưng gắn cờ DYOR
LOW_LIQUIDITY_FLAG_USD = 100_000


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


def _base_symbol(pair: dict) -> str:
    return str((pair.get("baseToken") or {}).get("symbol") or "").upper()


def _quote_symbol(pair: dict) -> str:
    return str((pair.get("quoteToken") or {}).get("symbol") or "").upper()


def _symbol_matches(pair: dict, entry: dict) -> bool:
    """Chốt chặn nhầm token: symbol thực tế phải khớp symbol khai báo."""
    expected_base = str(entry.get("baseSymbol") or "").upper().strip().lstrip("$")
    expected_quote = str(entry.get("quoteSymbol") or "").upper().strip().lstrip("$")
    if expected_base and _base_symbol(pair).lstrip("$") != expected_base:
        return False
    if expected_quote and _quote_symbol(pair).lstrip("$") != expected_quote:
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
    """Fetch MỘT pair (dùng cho diagnose). Production dùng fetch_pairs_batch."""
    chain_id = entry.get("chainId")
    pair_address = entry.get("pairAddress")
    if chain_id and pair_address:
        data = _get_json(f"/latest/dex/pairs/{chain_id}/{pair_address}")
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        pair = pairs[0]
        return pair if _symbol_matches(pair, entry) else None

    # Search-only: CHỈ cho diagnosis/khám phá — production phải pin pairAddress.
    query = entry.get("query") or entry.get("name")
    if not query:
        return None
    data = _get_json("/latest/dex/search", {"q": query})
    return _best_pair(data.get("pairs") or [], entry)


def fetch_pairs_batch(watchlist: list[dict]) -> tuple[dict[str, dict], int]:
    """
    Fetch mọi pair pin theo batch: gom pairAddress theo chain, mỗi chain
    1 request (tối đa 30 address). Trả (map "chain:address(lower)" -> pair dict,
    số request API fail). api_errors > 0 = thiếu dữ liệu vì API, KHÔNG phải
    thị trường im — caller phải phân biệt hai trạng thái này.
    Entry search-only bị bỏ qua (production-only path).
    """
    by_chain: dict[str, list[str]] = {}
    for entry in watchlist:
        chain = entry.get("chainId")
        addr = entry.get("pairAddress")
        if chain and addr:
            by_chain.setdefault(chain.lower(), []).append(addr)

    found: dict[str, dict] = {}
    api_errors = 0
    for chain, addresses in by_chain.items():
        for i in range(0, len(addresses), BATCH_MAX_ADDRESSES):
            chunk = addresses[i:i + BATCH_MAX_ADDRESSES]
            try:
                data = _get_json(f"/latest/dex/pairs/{chain}/{','.join(chunk)}")
            except Exception as exc:
                api_errors += 1
                logger.warning("DEXScreener batch fetch failed (%s): %s", chain, exc)
                continue
            for pair in data.get("pairs") or []:
                key = f"{str(pair.get('chainId', '')).lower()}:{str(pair.get('pairAddress', '')).lower()}"
                found[key] = pair
    return found, api_errors


def _entry_cfg(entry: dict, cfg: dict) -> dict:
    """Ngưỡng hiệu lực cho một entry: global, override được per-pair."""
    return {
        "min_liquidity_usd": entry.get("min_liquidity_usd", cfg.get("min_liquidity_usd")),
        "min_volume_usd": {**(cfg.get("min_volume_usd") or {}), **(entry.get("min_volume_usd") or {})},
        "thresholds_pct": {**(cfg.get("thresholds_pct") or {}), **(entry.get("thresholds_pct") or {})},
    }


def _trigger(pair: dict, cfg: dict) -> Optional[tuple[str, float]]:
    """Khung mạnh nhất vượt ngưỡng (qua gate liquidity + volume), hoặc None."""
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


# Cooldown sàn theo khung: move h24 còn vượt ngưỡng suốt ngày không được
# re-alert mỗi 15 phút — chỉ nhắc lại khi sang bucket khung mới hoặc đảo chiều
# (direction nằm trong dedup_key nên flip luôn alert được ngay).
_HORIZON_COOLDOWN_MIN = {"m5": 5, "h1": 60, "h6": 360, "h24": 1440}


def _bucket(now: datetime, cooldown_minutes: int) -> str:
    """Floor timestamp theo bucket size (epoch-aligned, hoạt động với mọi cỡ phút)."""
    cooldown = max(1, int(cooldown_minutes))
    floored = int(now.timestamp()) // (cooldown * 60) * (cooldown * 60)
    return datetime.fromtimestamp(floored, tz=timezone.utc).strftime("%Y%m%d%H%M")


def build_signal(pair: dict, horizon: str, change_pct: float, cfg: dict,
                 now: Optional[datetime] = None) -> PairSignal:
    now = now or datetime.now(timezone.utc)
    price_change = pair.get("priceChange") or {}
    txns = (pair.get("txns") or {}).get(horizon) or {}
    chain = str(pair.get("chainId") or "")
    address = str(pair.get("pairAddress") or "")
    direction = "UP" if change_pct > 0 else "DOWN"
    cooldown = max(int(cfg.get("cooldown_minutes", 15)), _HORIZON_COOLDOWN_MIN.get(horizon, 15))
    bucket = _bucket(now, cooldown)
    liquidity = _num((pair.get("liquidity") or {}).get("usd"))

    return PairSignal(
        chain_id=chain,
        dex_id=str(pair.get("dexId") or ""),
        pair_address=address,
        base_symbol=_base_symbol(pair) or "TOKEN",
        quote_symbol=_quote_symbol(pair) or "QUOTE",
        base_address=str((pair.get("baseToken") or {}).get("address") or "") or None,
        url=pair.get("url") or f"https://dexscreener.com/{chain}/{address}",
        horizon=horizon,
        change_pct=change_pct,
        price_usd=_num(pair.get("priceUsd")),
        volume_usd=_num((pair.get("volume") or {}).get(horizon)),
        liquidity_usd=liquidity,
        buys=int(_num(txns.get("buys"))),
        sells=int(_num(txns.get("sells"))),
        changes={h: _num(price_change.get(h)) for h in HORIZONS if price_change.get(h) is not None},
        fdv=_num(pair.get("fdv")) or None,
        market_cap=_num(pair.get("marketCap")) or None,
        observed_at=now,
        dedup_key=f"dex:{chain}:{address}:{horizon}:{direction}:{bucket}",
        low_liquidity=liquidity < LOW_LIQUIDITY_FLAG_USD,
    )


def scan_watchlist(config_path: str | Path = CONFIG_PATH) -> tuple[list[PairSignal], int]:
    """
    Quét toàn bộ watchlist. Trả (danh sách PairSignal vượt ngưỡng, api_errors).
    API fail từng phần → bỏ qua phần đó, không sập pipeline, NHƯNG phải đếm
    api_errors để heartbeat phân biệt "thị trường im" với "API sập".
    """
    cfg = load_config(config_path)
    if not cfg.get("enabled", True):
        return [], 0

    watchlist = cfg.get("watchlist") or []
    pairs_map, api_errors = fetch_pairs_batch(watchlist)

    signals: list[PairSignal] = []
    for entry in watchlist:
        name = entry.get("name") or entry.get("pairAddress") or str(entry)
        try:
            chain = str(entry.get("chainId") or "").lower()
            addr = str(entry.get("pairAddress") or "").lower()
            pair = pairs_map.get(f"{chain}:{addr}")
            if pair is None and not addr:
                logger.warning("DEXScreener: entry %s chưa pin pairAddress — bỏ qua (production cần pin).", name)
                continue
            if pair is None:
                logger.warning("DEXScreener: không có dữ liệu pair cho %s", name)
                continue
            if not _symbol_matches(pair, entry):
                logger.error("DEXScreener: SYMBOL MISMATCH %s — API trả %s/%s, config khai %s/%s. Bỏ qua.",
                             name, _base_symbol(pair), _quote_symbol(pair),
                             entry.get("baseSymbol"), entry.get("quoteSymbol"))
                continue

            eff = _entry_cfg(entry, cfg)
            hit = _trigger(pair, eff)
            if not hit:
                continue
            horizon, change = hit
            signals.append(build_signal(pair, horizon, change, cfg))
        except Exception as exc:
            logger.warning("DEXScreener scan skipped for %s: %s", name, exc)
    logger.info("DEXScreener signals: %s (api_errors=%s)", len(signals), api_errors)
    return signals, api_errors


# Smoke test scanner: py -3 scripts/diagnose_dexscreener.py (read-only, đầy đủ hơn)
