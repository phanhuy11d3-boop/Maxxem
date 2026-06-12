---
name: env-console-cp1252
description: Windows console defaults to cp1252 — diagnose scripts crash with UnicodeEncodeError unless PYTHONIOENCODING=utf-8 is set
metadata:
  type: project
---

Always run audit scripts with `PYTHONIOENCODING=utf-8` prefixed, e.g. `PYTHONIOENCODING=utf-8 py -3 scripts/diagnose_outbox.py` (POSIX/bash syntax — the Bash tool here is bash, not PowerShell, so `$env:VAR=...` syntax fails).

**Why:** Windows console defaults to cp1252; script output contains Vietnamese diacritics/emoji and pair symbols can contain unicode — without the prefix the script crashes mid-output with `UnicodeEncodeError: 'charmap' codec can't encode character`. Confirmed 2026-06-10, still applies to the v3 DEX-only scripts.

**How to apply:** Prefix every `py -3 scripts/*.py` invocation that prints DB rows. Also note: scripts read `DATABASE_URL` from process env — load `.env` first when running from a bare shell (main.py and scripts never read .env themselves).
