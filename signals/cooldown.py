"""Cooldown bucket helpers."""

from __future__ import annotations

from datetime import datetime, timezone


HORIZON_COOLDOWN_MIN = {"m5": 5, "h1": 60, "h6": 360, "h24": 1440}


def bucket(now: datetime, cooldown_minutes: int) -> str:
    cooldown = max(1, int(cooldown_minutes))
    floored = int(now.timestamp()) // (cooldown * 60) * (cooldown * 60)
    return datetime.fromtimestamp(floored, tz=timezone.utc).strftime("%Y%m%d%H%M")


def effective_cooldown(horizon: str, configured_minutes: int) -> int:
    return max(int(configured_minutes), HORIZON_COOLDOWN_MIN.get(horizon, 15))

