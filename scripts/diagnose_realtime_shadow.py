"""Read-only realtime shadow status check."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapers.dexscreener import load_config  # noqa: E402
from sources.dexscreener_realtime_shadow import load_realtime_shadow_config  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    shadow = load_realtime_shadow_config(cfg)
    print("=" * 72)
    print("REALTIME SHADOW STATUS (read-only)")
    print("=" * 72)
    print(f"enabled       : {shadow.enabled}")
    print(f"provider      : {shadow.provider or '-'}")
    print(f"write_signals : {shadow.write_signals}")
    print(f"send_telegram : {shadow.send_telegram}")
    print(f"safe          : {shadow.safe}")
    if not shadow.enabled:
        print("\nstatus: DISABLED - production uses DEXScreener REST only.")
    elif shadow.safe:
        print("\nstatus: SHADOW - safe; no production writes/sends.")
    else:
        print("\nstatus: UNSAFE CONFIG - shadow must not write signals or send Telegram.")


if __name__ == "__main__":
    main()

