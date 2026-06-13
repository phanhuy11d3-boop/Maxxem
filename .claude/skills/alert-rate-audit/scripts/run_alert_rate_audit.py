"""Run read-only alert-rate diagnostics from the skill directory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
COMMANDS = [
    ["py", "-3", "scripts/diagnose_alert_rate.py"],
    ["py", "-3", "scripts/diagnose_outbox.py"],
]


def main() -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    failed = 0
    for cmd in COMMANDS:
        print("\n$ " + " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=ROOT, env=env, text=True)
        failed += int(proc.returncode != 0)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
