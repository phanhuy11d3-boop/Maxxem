# -*- coding: utf-8 -*-
"""PreToolUse guard for read-only audit agents.

Claude Code pipes the hook payload as JSON on stdin. We inspect the shell
command about to run and exit 2 (block, with feedback on stderr) when it
matches a forbidden group passed on the CLI, e.g.:

    py -3 scripts/hooks/guard_readonly.py --block unstick marktg sqlwrite
"""
import json
import re
import sys

GROUPS = {
    "unstick": (
        re.compile(r"unstick_retry\.py", re.I),
        "Blocked by guard_readonly hook: scripts/unstick_retry.py WRITES to the "
        "production DB (resets retry_count). This agent is read-only - report the "
        "stuck rows and ask the main session to run it.",
    ),
    "marktg": (
        re.compile(r"diagnose_marktg\.py", re.I),
        "Blocked by guard_readonly hook: scripts/diagnose_marktg.py live-fires a "
        "real Telegram message and UPDATEs the DB. This agent is read-only - ask "
        "the main session to run it.",
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
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed/missing payload: never block blindly
    command = (payload.get("tool_input") or {}).get("command") or ""
    for name in blocks:
        entry = GROUPS.get(name)
        if entry and entry[0].search(command):
            print(entry[1], file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
