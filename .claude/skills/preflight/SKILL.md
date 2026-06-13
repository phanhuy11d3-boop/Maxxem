---
name: preflight
description: Dry smoke-test the repo before committing changes that touch runtime, scrapers, storage, or workflows. Runs unit tests, compile checks, and DEX diagnosis by default; live production pipeline requires --live.
disable-model-invocation: true
allowed-tools: Bash(py -3 .claude/skills/preflight/scripts/*)
shell: powershell
---

# Preflight - smoke before commit

This is the ops-manager smoke procedure as one command. It is dry by default:
no Telegram sends and no intentional production DB writes. Live pipeline stages
exist only behind `--live`.

## Dry Run

```powershell
py -3 .claude/skills/preflight/scripts/run_preflight.py
```

Dry stages, in order:

1. `pytest tests/unit -q` — required
2. `py -3 -m py_compile ...` — required
3. `py -3 scripts/diagnose_claude_config.py` — required, read-only skill/subagent format diagnosis
4. `py -3 scripts/diagnose_dexscreener.py` — required, read-only market scanner diagnosis

## Live Run

```powershell
py -3 .claude/skills/preflight/scripts/run_preflight.py --live
```

Live stages append:

1. `py -3 main.py` — the real DEX-only pipeline (writes `signals`, may send Telegram)

## Interpret

- **ALL PASS** on dry run → safe enough for a normal commit gate. It does not prove live Telegram delivery.
- **ALL PASS** on live run → pipeline executed without crashing. Also eyeball `storage/state.json` for the error counters of the last run (`db` / `telegram` should be 0).
- **ABORT** → do not commit. The script prints the last 15 lines of the failing stage; diagnose from there. For pipeline-internal failures, delegate to the matching specialist agent (ops-manager for orchestration, ingestion-scout for scanner, db-auditor for storage, notifier-broadcaster for delivery).
- Telegram sends during `--live` are real but bounded by the 30-minute stale window — mention any sends in the report so the operator is not surprised by channel messages.
