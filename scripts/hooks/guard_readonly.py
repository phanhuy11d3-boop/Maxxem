# -*- coding: utf-8 -*-
"""PreToolUse guard for read-only audit agents.

Claude Code pipes the hook payload as JSON on stdin. We inspect the shell
command about to run and exit 2 (block, with feedback on stderr) when it
matches a forbidden group passed on the CLI, e.g.:

    py -3 scripts/hooks/guard_readonly.py --block sqlwrite livefire
"""
import json
import re
import sys

GROUPS = {
    "livefire": (
        re.compile(r"(notifier\.py.*--live|main\.py\b|run_preflight\.py.*--live)", re.I),
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


def main() -> None:
    blocks = [a for a in sys.argv[1:] if a != "--block"]
    try:
        # utf-8-sig: chịu được BOM (vd khi payload đi qua pipe PowerShell).
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception:
        # Guard an ninh phải fail-CLOSED: payload không đọc được nghĩa là
        # không thể xác minh lệnh sắp chạy -> chặn, không cho chạy mù.
        print(
            "guard_readonly: cannot parse hook payload - failing CLOSED. "
            "This read-only agent must not run shell commands unverified.",
            file=sys.stderr,
        )
        sys.exit(2)
    command = (payload.get("tool_input") or {}).get("command") or ""
    for name in blocks:
        entry = GROUPS.get(name)
        if entry and entry[0].search(command):
            print(entry[1], file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
