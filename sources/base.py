"""Shared source contracts.

Source adapters turn raw provider payloads into PairSnapshot objects. Trigger
logic consumes snapshots, not provider-specific dictionaries, which keeps the
scanner path testable and lets new sources run in shadow mode without touching
Telegram delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol


SOURCE_DEXSCREENER_REST = "dexscreener_rest"


@dataclass(frozen=True)
class PairSnapshot:
    source: str
    chain_id: str
    dex_id: str
    pair_address: str
    base_symbol: str
    quote_symbol: str
    base_address: str | None
    url: str
    price_usd: float
    liquidity_usd: float
    volume: Mapping[str, float] = field(default_factory=dict)
    price_change: Mapping[str, float] = field(default_factory=dict)
    txns: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    fdv: float | None = None
    market_cap: float | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceHealth:
    source: str
    chain_id: str
    stream_id: str
    status: str
    last_seen_at: datetime | None = None
    last_error: str | None = None
    messages_seen: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SourceAdapter(Protocol):
    source_name: str

    def fetch_snapshots(self, watchlist: list[dict]) -> tuple[dict[str, PairSnapshot], int, list[SourceHealth]]:
        """Return keyed snapshots, API error count, and health updates."""

