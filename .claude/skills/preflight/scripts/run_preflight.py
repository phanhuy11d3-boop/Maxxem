# -*- coding: utf-8 -*-
"""Preflight smoke-test for orchestrator changes (v3 DEX-only).

Dry by default: unit tests -> compile core modules -> DEX diagnosis.
Use --live to append one real pipeline run.

WARNING: --live executes the REAL pipeline against the production DB
and Telegram outbox, subject to the 30-minute stale window.
"""
import argparse
import os
import subprocess
import sys
import time

CORE_COMPILE_FILES = [
    "main.py",
    "models/pair_signal.py",
    "models/scoring.py",
    "storage/postgres.py",
    "scrapers/dexscreener.py",
    "utils/notifier.py",
]

DRY_STAGES = [
    ("unit-tests", ["py", "-3", "-m", "pytest", "tests/unit", "-q"], True),
    ("compile-core", ["py", "-3", "-m", "py_compile", *CORE_COMPILE_FILES], True),
    ("diagnose-dexscreener", ["py", "-3", "scripts/diagnose_dexscreener.py"], True),
]

LIVE_STAGES = [
    ("pipeline", ["py", "-3", "main.py"], True),
]


def main():
    parser = argparse.ArgumentParser(description="CryptoSentinel preflight")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Append production DB/Telegram pipeline stages.",
    )
    args = parser.parse_args()

    stages = list(DRY_STAGES)
    if args.live:
        print("preflight: LIVE mode enabled - production DB/Telegram may be touched")
        stages.extend(LIVE_STAGES)
    else:
        print("preflight: dry mode - no intentional Telegram sends or DB writes")

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    results = []
    for name, cmd, required in stages:
        t0 = time.monotonic()
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=900)
        secs = time.monotonic() - t0
        ok = proc.returncode == 0
        results.append((name, ok, required))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} (exit={proc.returncode}, {secs:.0f}s)")
        if not ok:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-15:]
            for line in tail:
                print(f"    {line}")
            if required:
                print(f"preflight: ABORT - required stage '{name}' failed")
                sys.exit(1)

    failed_optional = [n for n, ok, req in results if not ok and not req]
    if failed_optional:
        print(f"preflight: PASS WITH WARNINGS - optional failed: {', '.join(failed_optional)}")
    else:
        print("preflight: ALL PASS")
    # PASS = "pipeline chạy không crash", KHÔNG phải "hệ thống đúng".
    # Nó không chứng minh: signal phân loại đúng, cadence đủ phủ, nguồn còn
    # sống, hay không miss tin. Các câu đó thuộc cadence-check / health-sweep.
    print("preflight: scope = does-it-run only (not signal quality, "
          "not cadence coverage, not source health)")


if __name__ == "__main__":
    main()
