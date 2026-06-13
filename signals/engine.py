"""Deterministic trigger engine for normalized pair snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from models.pair_signal import HORIZONS, PairSignal
from models.scoring import build_transmission_chain, compute_confidence
from signals.cooldown import bucket, effective_cooldown
from sources.base import PairSnapshot

LOW_LIQUIDITY_FLAG_USD = 100_000


@dataclass(frozen=True)
class TriggerDecision:
    horizon: str
    change_pct: float


def entry_config(entry: dict, cfg: dict) -> dict:
    return {
        "min_liquidity_usd": entry.get("min_liquidity_usd", cfg.get("min_liquidity_usd")),
        "min_volume_usd": {**(cfg.get("min_volume_usd") or {}), **(entry.get("min_volume_usd") or {})},
        "thresholds_pct": {**(cfg.get("thresholds_pct") or {}), **(entry.get("thresholds_pct") or {})},
    }


def evaluate_snapshot(snapshot: PairSnapshot, cfg: dict) -> Optional[TriggerDecision]:
    if snapshot.liquidity_usd < float(cfg.get("min_liquidity_usd") or 0):
        return None

    thresholds = cfg.get("thresholds_pct") or {}
    min_volume = cfg.get("min_volume_usd") or {}
    hits: list[TriggerDecision] = []
    for horizon in HORIZONS:
        change = float(snapshot.price_change.get(horizon, 0.0))
        threshold = float(thresholds.get(horizon) or 0.0)
        if threshold <= 0 or abs(change) < threshold:
            continue
        if float(snapshot.volume.get(horizon, 0.0)) < float(min_volume.get(horizon) or 0.0):
            continue
        hits.append(TriggerDecision(horizon=horizon, change_pct=change))
    if not hits:
        return None
    return max(hits, key=lambda item: abs(item.change_pct))


def build_signal_from_snapshot(
    snapshot: PairSnapshot,
    decision: TriggerDecision,
    cfg: dict,
    now: Optional[datetime] = None,
) -> PairSignal:
    now = now or datetime.now(timezone.utc)
    horizon = decision.horizon
    change_pct = decision.change_pct
    txns = snapshot.txns.get(horizon) or {}
    direction = "UP" if change_pct > 0 else "DOWN"
    cooldown = effective_cooldown(horizon, int(cfg.get("cooldown_minutes", 15)))
    changes = {h: float(snapshot.price_change[h]) for h in HORIZONS if h in snapshot.price_change}
    volume = float(snapshot.volume.get(horizon, 0.0))
    buys = int(txns.get("buys") or 0)
    sells = int(txns.get("sells") or 0)

    scoring_cfg = cfg.get("scoring") or {}
    confidence: Optional[int] = None
    transmission: Optional[str] = None
    if scoring_cfg.get("enabled", True):
        threshold_pct = float((cfg.get("thresholds_pct") or {}).get(horizon) or 0.0)
        min_vol_gate = float((cfg.get("min_volume_usd") or {}).get(horizon) or 0.0)
        confidence = compute_confidence(
            change_pct=change_pct,
            threshold_pct=threshold_pct,
            volume_usd=volume,
            min_volume_gate=min_vol_gate,
            liquidity_usd=snapshot.liquidity_usd,
            buys=buys,
            sells=sells,
            changes=changes,
            direction=direction,
            weights=scoring_cfg.get("weights"),
        )
        transmission = build_transmission_chain(
            direction=direction,
            volume_usd=volume,
            min_volume_gate=min_vol_gate,
            buys=buys,
            sells=sells,
            changes=changes,
        )

    return PairSignal(
        chain_id=snapshot.chain_id,
        dex_id=snapshot.dex_id,
        pair_address=snapshot.pair_address,
        base_symbol=snapshot.base_symbol,
        quote_symbol=snapshot.quote_symbol,
        base_address=snapshot.base_address,
        url=snapshot.url,
        horizon=horizon,
        change_pct=change_pct,
        price_usd=snapshot.price_usd,
        volume_usd=volume,
        liquidity_usd=snapshot.liquidity_usd,
        buys=buys,
        sells=sells,
        changes=changes,
        fdv=snapshot.fdv,
        market_cap=snapshot.market_cap,
        observed_at=now,
        dedup_key=(
            f"dex:{snapshot.chain_id}:{snapshot.pair_address}:"
            f"{horizon}:{direction}:{bucket(now, cooldown)}"
        ),
        low_liquidity=snapshot.liquidity_usd < LOW_LIQUIDITY_FLAG_USD,
        confidence_score=confidence,
        transmission_chain=transmission,
    )

