"""DEXScreener REST adapter.

This is the production source today. It batches pinned pair addresses per chain
and returns normalized PairSnapshot objects plus health updates for each chain.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from sources.base import PairSnapshot, SourceHealth, SOURCE_DEXSCREENER_REST
from sources.normalize import normalize_dexscreener_pair, snapshot_key, symbol_matches, num

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"
HTTP_TIMEOUT_S = 10
BATCH_MAX_ADDRESSES = 30


def get_json(path: str, params: Optional[dict] = None) -> Any:
    resp = requests.get(f"{BASE_URL}{path}", params=params or {}, timeout=HTTP_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


class DexScreenerRestSource:
    source_name = SOURCE_DEXSCREENER_REST

    def fetch_pair(self, entry: dict) -> Optional[dict]:
        chain_id = entry.get("chainId")
        pair_address = entry.get("pairAddress")
        if chain_id and pair_address:
            data = get_json(f"/latest/dex/pairs/{chain_id}/{pair_address}")
            pairs = data.get("pairs") or []
            if not pairs:
                return None
            pair = pairs[0]
            return pair if symbol_matches(pair, entry) else None

        query = entry.get("query") or entry.get("name")
        if not query:
            return None
        data = get_json("/latest/dex/search", {"q": query})
        return self._best_pair(data.get("pairs") or [], entry)

    def fetch_raw_pairs_batch(self, watchlist: list[dict]) -> tuple[dict[str, dict], int, list[SourceHealth]]:
        by_chain: dict[str, list[str]] = {}
        for entry in watchlist:
            chain = entry.get("chainId")
            addr = entry.get("pairAddress")
            if chain and addr:
                by_chain.setdefault(chain.lower(), []).append(addr)

        found: dict[str, dict] = {}
        api_errors = 0
        health: list[SourceHealth] = []
        now = datetime.now(timezone.utc)
        for chain, addresses in by_chain.items():
            chain_seen = 0
            chain_error: str | None = None
            for i in range(0, len(addresses), BATCH_MAX_ADDRESSES):
                chunk = addresses[i:i + BATCH_MAX_ADDRESSES]
                try:
                    data = get_json(f"/latest/dex/pairs/{chain}/{','.join(chunk)}")
                except Exception as exc:
                    api_errors += 1
                    chain_error = str(exc)
                    logger.warning("DEXScreener batch fetch failed (%s): %s", chain, exc)
                    continue
                for pair in data.get("pairs") or []:
                    key = snapshot_key(pair.get("chainId"), pair.get("pairAddress"))
                    found[key] = pair
                    chain_seen += 1

            health.append(
                SourceHealth(
                    source=self.source_name,
                    chain_id=chain,
                    stream_id="rest_batch",
                    status="healthy" if chain_error is None else ("degraded" if chain_seen else "unhealthy"),
                    last_seen_at=now if chain_seen else None,
                    last_error=chain_error,
                    messages_seen=chain_seen,
                    updated_at=now,
                )
            )
        return found, api_errors, health

    def fetch_snapshots(self, watchlist: list[dict]) -> tuple[dict[str, PairSnapshot], int, list[SourceHealth]]:
        raw_pairs, api_errors, health = self.fetch_raw_pairs_batch(watchlist)
        snapshots = {key: normalize_dexscreener_pair(pair) for key, pair in raw_pairs.items()}
        return snapshots, api_errors, health

    def _best_pair(self, candidates: list[dict], entry: dict) -> Optional[dict]:
        chain_id = entry.get("chainId")
        if chain_id:
            candidates = [
                p for p in candidates
                if str(p.get("chainId", "")).lower() == chain_id.lower()
            ]
        candidates = [p for p in candidates if symbol_matches(p, entry)]
        if not candidates:
            return None
        return max(candidates, key=lambda p: num((p.get("liquidity") or {}).get("usd")))

