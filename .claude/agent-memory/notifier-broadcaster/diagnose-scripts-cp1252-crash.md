---
name: diagnose-scripts-cp1252-crash
description: diagnose_telegram2.py still crashes (exit 1) on cp1252 consoles for CJK titles; diagnose_telegram.py was patched (stdout.reconfigure line 26)
metadata:
  type: project
---

`scripts/diagnose_telegram2.py` raises `UnicodeEncodeError` (cp1252) when printing article titles containing CJK punctuation (e.g. `「` U+300C from Lookonchain headlines), truncating the final "10 newest actionable" section and exiting 1 even when the DB is healthy. `scripts/diagnose_telegram.py` was FIXED (verified 2026-06-11): it has `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at line 26; diagnose_telegram2.py was never given the same patch.

**Why:** Windows console defaults to cp1252; diagnose_telegram2.py prints raw titles without reconfiguring stdout.
**How to apply:** Exit code 1 from diagnose_telegram2.py does NOT imply a delivery failure — read the printed numbers above the traceback (all count sections print before the crash; only the per-title list truncates). Env-var prefixes like `$env:PYTHONIOENCODING='utf-8'; py -3 ...` and `py -3 -X utf8 ...` are DENIED by this agent's permission rules — only the bare `py -3 scripts/diagnose_telegram*.py` invocations are allowed, so the crash cannot be worked around at the shell; permanent fix is adding the same `reconfigure` line to diagnose_telegram2.py.
