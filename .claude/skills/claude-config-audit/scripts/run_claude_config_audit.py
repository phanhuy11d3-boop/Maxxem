"""Run Claude skill/subagent format validation from the skill directory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def main() -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        ["py", "-3", "scripts/diagnose_claude_config.py"],
        cwd=ROOT,
        env=env,
        text=True,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
