# -*- coding: utf-8 -*-
"""Preflight smoke-test for orchestrator changes.

Runs, in order: unit tests -> legacy pipeline -> agentic pipeline,
prints one summary line per stage and exits non-zero on first failure
of a REQUIRED stage.

WARNING: stages 2 and 3 execute the REAL pipeline against the production
DB (and Telegram outbox, subject to the 30-minute stale window). That is
the documented ops-manager smoke procedure, but it is not a dry run.
"""
import os
import subprocess
import sys
import time

STAGES = [
    ("unit-tests", ["py", "-3", "-m", "pytest", "tests/unit", "-q"], True),
    ("legacy-pipeline", ["py", "-3", "main.py", "--legacy"], True),
    # agentic is opt-in and must fall back to legacy on failure; its own
    # crash is still a finding, so we run it but report rather than infer.
    ("agentic-pipeline", ["py", "-3", "main.py", "--agentic"], False),
]


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    results = []
    for name, cmd, required in STAGES:
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
