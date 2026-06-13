"""Tests cho PreToolUse guard read-only (scripts/hooks/guard_readonly.py).

Chạy guard như Claude Code: pipe payload JSON qua stdin, kiểm exit code
(0 = cho phép, 2 = chặn). Khóa cả silent-bug mới vá: agent read-only KHÔNG
được sửa file ngoài .claude/agent-memory/.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "hooks" / "guard_readonly.py"


def _run(blocks: list[str], payload: dict) -> int:
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--block", *blocks],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
    )
    return proc.returncode


def _cmd(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _write(path: str, tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def test_sqlwrite_blocked():
    assert _run(["sqlwrite", "livefire"], _cmd("psql -c 'DELETE FROM signals'")) == 2


def test_livefire_blocked():
    assert _run(["sqlwrite", "livefire"], _cmd("py -3 main.py")) == 2
    assert _run(["sqlwrite", "livefire"], _cmd("py -3 utils/notifier.py --live")) == 2
    assert _run(["sqlwrite", "livefire"], _cmd("py -3 scripts/daily_digest.py --live")) == 2


def test_readonly_command_allowed():
    assert _run(["sqlwrite", "livefire"], _cmd("py -3 scripts/diagnose_outbox.py")) == 0
    assert _run(["sqlwrite", "livefire"], _cmd("py -3 scripts/diagnose_scores.py")) == 0


def test_filewrite_outside_memory_blocked():
    assert _run(["filewrite"], _write("storage/postgres.py")) == 2
    assert _run(["filewrite"], _write("models/scoring.py", tool="Edit")) == 2


def test_filewrite_into_agent_memory_allowed():
    assert _run(["filewrite"], _write(".claude/agent-memory/db-auditor/MEMORY.md")) == 0
    win = _write("C:\\Tool\\crypto-sentinel\\.claude\\agent-memory\\db-auditor\\note.md")
    assert _run(["filewrite"], win) == 0


def test_unparsable_payload_fails_closed():
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--block", "sqlwrite"],
        input=b"not json",
        capture_output=True,
    )
    assert proc.returncode == 2
