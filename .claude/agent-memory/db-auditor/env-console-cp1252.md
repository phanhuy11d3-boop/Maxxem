---
name: env-console-cp1252
description: Windows console defaults to cp1252 — diagnose scripts crash with UnicodeEncodeError unless PYTHONIOENCODING=utf-8 is set
metadata:
  type: project
---

Always run audit scripts with `PYTHONIOENCODING=utf-8` prefixed, e.g. `PYTHONIOENCODING=utf-8 py -3 scripts/diagnose_telegram.py` (POSIX/bash syntax — the Bash tool here is bash, not PowerShell, so `$env:VAR=...` syntax fails).

**Why:** Windows console defaults to cp1252; article titles contain CJK/unicode chars (e.g. `「`), and `scripts/diagnose_telegram.py` crashes mid-output with `UnicodeEncodeError: 'charmap' codec can't encode character` in section 5 without it. Confirmed 2026-06-10.

**How to apply:** Prefix every `py -3 scripts/*.py` invocation that prints DB rows. See [[outbox-baseline-2026-06-10]] for the healthy numbers these scripts should report.
