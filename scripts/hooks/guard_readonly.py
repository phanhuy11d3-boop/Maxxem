# -*- coding: utf-8 -*-
"""PreToolUse guard for read-only audit agents.

Hai trục enforcement (chọn qua --block):
  * command groups (`sqlwrite`, `livefire`) — soi lệnh shell Bash/PowerShell.
  * `filewrite` — soi Write/Edit/MultiEdit/NotebookEdit; CHỈ cho phép ghi vào
    bộ nhớ riêng của agent (`.claude/agent-memory/`), chặn mọi đường khác.
    (memory: project tự bật Write/Edit để agent tự quản MEMORY.md — không bịt
    hẳn được, nên giới hạn phạm vi ghi thay vì cấm tuyệt đối.)

Claude Code pipe payload hook dạng JSON qua stdin. Exit 2 = chặn, feedback ra
stderr. Ví dụ frontmatter agent:

    py -3 scripts/hooks/guard_readonly.py --block sqlwrite livefire   # matcher Bash|PowerShell
    py -3 scripts/hooks/guard_readonly.py --block filewrite           # matcher Write|Edit|...
"""
import json
import re
import sys

COMMAND_GROUPS = {
    "livefire": (
        re.compile(r"(notifier\.py.*--live|main\.py\b|run_preflight\.py.*--live|daily_digest\.py.*--live)", re.I),
        "Blocked by guard_readonly hook: this command live-fires the production "
        "pipeline or sends a real Telegram message. This agent is read-only - "
        "report the need and let the main session run it.",
    ),
    "sqlwrite": (
        re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b", re.I),
        "Blocked by guard_readonly hook: SQL write keyword detected and this agent "
        "is read-only. If you were only searching code for these words, use the "
        "Grep tool instead of a shell command.",
    ),
}

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Đường duy nhất agent read-only được phép ghi: bộ nhớ riêng của chính nó.
_MEMORY_OK = re.compile(r"(^|/)\.claude/agent-memory/", re.I)


def _block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    blocks = [a for a in sys.argv[1:] if a != "--block"]
    try:
        # utf-8-sig: chịu được BOM (vd khi payload đi qua pipe PowerShell).
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception:
        # Guard an ninh phải fail-CLOSED: payload không đọc được nghĩa là
        # không thể xác minh hành động sắp chạy -> chặn, không cho chạy mù.
        _block(
            "guard_readonly: cannot parse hook payload - failing CLOSED. "
            "This read-only agent must not run unverified tool calls."
        )

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    # Trục file-write: chặn sửa file ngoài agent-memory cho agent read-only.
    if "filewrite" in blocks and tool_name in WRITE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        norm = path.replace("\\", "/")
        if not _MEMORY_OK.search(norm):
            _block(
                "Blocked by guard_readonly hook: this read-only agent may only "
                "write under .claude/agent-memory/. Report the change and let the "
                "main session apply it."
            )
        sys.exit(0)

    # Trục command: Bash/PowerShell.
    command = tool_input.get("command") or ""
    for name in blocks:
        entry = COMMAND_GROUPS.get(name)
        if entry and entry[0].search(command):
            _block(entry[1])
    sys.exit(0)


if __name__ == "__main__":
    main()
