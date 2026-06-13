"""DEXScreener price-movement scanner.

This module is the compatibility facade for the production scanner. The actual
source fetch/normalization lives in ``sources/`` and deterministic trigger logic
lives in ``signals/``. Keeping this facade stable lets diagnostics and tests keep
using the older function names while the internals become source-agnostic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from models.pair_signal import PairSignal
from signals.cooldown import bucket as _cooldown_bucket
from signals.engine import (
    LOW_LIQUIDITY_FLAG_USD,
    TriggerDecision,
    build_signal_from_snapshot,
    entry_config,
    evaluate_snapshot,
)
from sources.dexscreener_rest import (
    BASE_URL,
    BATCH_MAX_ADDRESSES,
    HTTP_TIMEOUT_S,
    DexScreenerRestSource,
    get_json,
)
from sources.normalize import (
    base_symbol as _base_symbol_from_pair,
    normalize_dexscreener_pair,
    norm_symbol as _normalize_symbol,
    num as _normalize_num,
    quote_symbol as _quote_symbol_from_pair,
    snapshot_key,
    symbol_matches as _snapshot_symbol_matches,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dexscreener.yaml"
_REST_SOURCE = DexScreenerRestSource()


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
    return get_json(path, params=params)


def _num(value: Any, default: float = 0.0) -> float:
    return _normalize_num(value, default=default)


def _base_symbol(pair: dict) -> str:
    return _base_symbol_from_pair(pair)


def _quote_symbol(pair: dict) -> str:
    return _quote_symbol_from_pair(pair)


def _norm_symbol(raw: str) -> str:
    return _normalize_symbol(raw)


def _symbol_matches(pair: dict, entry: dict) -> bool:
    return _snapshot_symbol_matches(pair, entry)


def _best_pair(candidates: list[dict], entry: dict) -> Optional[dict]:
    return _REST_SOURCE._best_pair(candidates, entry)


def fetch_pair(entry: dict) -> Optional[dict]:
    """Fetch one pair. Production scanning uses ``fetch_pairs_batch``."""
    return _REST_SOURCE.fetch_pair(entry)


def fetch_pairs_batch(watchlist: list[dict]) -> tuple[dict[str, dict], int]:
    """Fetch pinned pairs in batches per chain and return raw DEXScreener pairs."""
    raw_pairs, api_errors, _health = _REST_SOURCE.fetch_raw_pairs_batch(watchlist)
    return raw_pairs, api_errors


def _entry_cfg(entry: dict, cfg: dict) -> dict:
    return entry_config(entry, cfg)


def _trigger(pair: dict, cfg: dict) -> Optional[tuple[str, float]]:
    decision = evaluate_snapshot(normalize_dexscreener_pair(pair), cfg)
    if not decision:
        return None
    return decision.horizon, decision.change_pct


def _bucket(now: datetime, cooldown_minutes: int) -> str:
    return _cooldown_bucket(now, cooldown_minutes)


def build_signal(
    pair: dict,
    horizon: str,
    change_pct: float,
    cfg: dict,
    now: Optional[datetime] = None,
) -> PairSignal:
    return build_signal_from_snapshot(
        normalize_dexscreener_pair(pair),
        TriggerDecision(horizon=horizon, change_pct=change_pct),
        cfg,
        now=now,
    )


def _record_source_health_safely(health_updates: list) -> None:
    """Best-effort health persistence; scanner output must not depend on DB writes."""
    if not health_updates:
        return
    try:
        from storage.postgres import record_source_health

        for health in health_updates:
            record_source_health(health)
    except Exception as exc:
        logger.debug("Source health update skipped: %s", exc)


def scan_watchlist(
    config_path: str | Path = CONFIG_PATH,
    *,
    record_health: bool = False,
) -> tuple[list[PairSignal], int]:
    """Scan the full watchlist and return ``(signals, api_errors)``."""
    cfg = load_config(config_path)
    if not cfg.get("enabled", True):
        return [], 0

    watchlist = cfg.get("watchlist") or []
    snapshots, api_errors, health = _REST_SOURCE.fetch_snapshots(watchlist)
    if record_health:
        _record_source_health_safely(health)

    signals: list[PairSignal] = []
    for entry in watchlist:
        name = entry.get("name") or entry.get("pairAddress") or str(entry)
        try:
            chain = str(entry.get("chainId") or "").lower()
            addr = str(entry.get("pairAddress") or "").lower()
            snapshot = snapshots.get(snapshot_key(chain, addr))
            raw_pair = dict(snapshot.raw) if snapshot else None
            if raw_pair is None and not addr:
                logger.warning(
                    "DEXScreener: entry %s is search-only; skipping production path.",
                    name,
                )
                continue
            if raw_pair is None:
                logger.warning("DEXScreener: no pair data for %s", name)
                continue
            if not _symbol_matches(raw_pair, entry):
                logger.error(
                    "DEXScreener: SYMBOL MISMATCH %s - API returned %s/%s, config says %s/%s. Skipping.",
                    name,
                    _base_symbol(raw_pair),
                    _quote_symbol(raw_pair),
                    entry.get("baseSymbol"),
                    entry.get("quoteSymbol"),
                )
                continue

            eff = _entry_cfg(entry, cfg)
            decision = evaluate_snapshot(snapshot, eff)
            if not decision:
                continue
            signals.append(build_signal_from_snapshot(snapshot, decision, {**cfg, **eff}))
        except Exception as exc:
            logger.warning("DEXScreener scan skipped for %s: %s", name, exc)
    logger.info("DEXScreener signals: %s (api_errors=%s)", len(signals), api_errors)
    return signals, api_errors


# Smoke test scanner: py -3 scripts/diagnose_dexscreener.py (read-only).
