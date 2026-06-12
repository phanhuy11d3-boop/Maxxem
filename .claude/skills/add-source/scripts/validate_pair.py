# -*- coding: utf-8 -*-
"""Validate a DEX pair against the live DEXScreener API before watchlisting.

Usage:
    py -3 validate_pair.py <chain> <pairAddress>
    py -3 validate_pair.py --search "WIF/SOL"

Read-only: chỉ GET API public, không ghi DB, không gửi Telegram.
Verdict:
    GOOD — pair tồn tại, liquidity >= $250k, có volume 24h
    WARN — pair tồn tại nhưng liquidity thấp (alert sẽ gắn cờ DYOR) hoặc volume mỏng
    BAD  — không tìm thấy pair / API lỗi / số liệu rỗng
"""
import sys

import requests

BASE_URL = "https://api.dexscreener.com"
GOOD_LIQUIDITY_USD = 250_000
MIN_VOLUME_24H_USD = 50_000


def _fmt(value) -> str:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.2f}"


def describe(pair: dict) -> None:
    base = (pair.get("baseToken") or {}).get("symbol")
    quote = (pair.get("quoteToken") or {}).get("symbol")
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    print(f"  pair      : {base}/{quote}")
    print(f"  chainId   : {pair.get('chainId')}")
    print(f"  dexId     : {pair.get('dexId')}")
    print(f"  address   : {pair.get('pairAddress')}")
    print(f"  priceUsd  : {pair.get('priceUsd')}")
    print(f"  liquidity : {_fmt(liq)}")
    print(f"  vol 24h   : {_fmt(vol24)}")
    print(f"  url       : {pair.get('url')}")

    if liq >= GOOD_LIQUIDITY_USD and vol24 >= MIN_VOLUME_24H_USD:
        print("  verdict   : GOOD")
    elif liq > 0:
        reasons = []
        if liq < GOOD_LIQUIDITY_USD:
            reasons.append(f"liquidity < {_fmt(GOOD_LIQUIDITY_USD)}")
        if vol24 < MIN_VOLUME_24H_USD:
            reasons.append(f"vol24h < {_fmt(MIN_VOLUME_24H_USD)}")
        print(f"  verdict   : WARN ({'; '.join(reasons)})")
    else:
        print("  verdict   : BAD (no liquidity data)")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    try:
        if args[0] == "--search":
            query = " ".join(args[1:])
            data = requests.get(
                f"{BASE_URL}/latest/dex/search", params={"q": query}, timeout=10
            ).json()
            pairs = sorted(
                data.get("pairs") or [],
                key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
                reverse=True,
            )[:5]
            if not pairs:
                print(f"verdict: BAD — search '{query}' trả 0 pair")
                sys.exit(1)
            print(f"Top {len(pairs)} pair theo liquidity cho '{query}':")
            for i, pair in enumerate(pairs, 1):
                print(f"\n[{i}]")
                describe(pair)
            print("\nPin pairAddress của pool canonical (thường là pool liquidity cao nhất).")
        else:
            chain, address = args[0], args[1]
            data = requests.get(
                f"{BASE_URL}/latest/dex/pairs/{chain}/{address}", timeout=10
            ).json()
            pairs = data.get("pairs") or []
            if not pairs:
                print(f"verdict: BAD — không có pair tại {chain}/{address}")
                sys.exit(1)
            describe(pairs[0])
    except requests.RequestException as exc:
        print(f"verdict: BAD — API error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
