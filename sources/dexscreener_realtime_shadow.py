"""Safe scaffold for a future DEXScreener realtime shadow source.

This module intentionally does not connect anywhere yet. It exists to make the
promotion boundary explicit: realtime starts as shadow, cannot write production
signals, and cannot send Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RealtimeShadowConfig:
    enabled: bool = False
    provider: str = ""
    write_signals: bool = False
    send_telegram: bool = False

    @property
    def safe(self) -> bool:
        return not self.write_signals and not self.send_telegram


def load_realtime_shadow_config(cfg: dict) -> RealtimeShadowConfig:
    sources = cfg.get("sources") or {}
    raw = sources.get("dexscreener_realtime") or {}
    return RealtimeShadowConfig(
        enabled=bool(raw.get("enabled", False)),
        provider=str(raw.get("provider") or ""),
        write_signals=bool(raw.get("write_signals", False)),
        send_telegram=bool(raw.get("send_telegram", False)),
    )

