---
name: preflight
description: Smoke-test the orchestrator before committing changes that touch main.py, agentic_runtime.py, processors/, scrapers/ or scraper.yml. Runs unit tests, the legacy pipeline, and the agentic pipeline in sequence.
disable-model-invocation: true
allowed-tools: Bash(py -3 .claude/skills/preflight/scripts/*)
---

# Preflight — smoke before commit

This is the ops-manager smoke procedure as one command. It is manual-only
(`disable-model-invocation: true`) because stages 2-3 run the REAL pipeline
against the production DB and Telegram outbox — never let the model trigger
it as a side effect.

## Run

```powershell
py -3 .claude/skills/preflight/scripts/run_preflight.py
```

Stages, in order (script aborts on required-stage failure):

1. `pytest tests/unit -q` — required
2. `py -3 main.py --legacy` — required (production-default path)
3. `py -3 main.py --agentic` — optional (opt-in path; must fall back to legacy on failure, so its crash is a warning, not an abort)

## Interpret

- **ALL PASS** → safe to commit. Also eyeball `storage/state.json` for the error counters of the last run (`db_errors` / `llm_errors` / `tg_errors` should be 0).
- **PASS WITH WARNINGS** (agentic failed) → committable for legacy-only changes, but report the agentic failure tail and check whether the fallback to legacy actually engaged.
- **ABORT** → do not commit. The script prints the last 15 lines of the failing stage; diagnose from there. For pipeline-internal failures, delegate to the matching specialist agent (ops-manager for orchestration, signal-analyst for LLM steps, db-auditor for storage).
- Telegram sends during stage 2/3 are real but bounded by the 30-minute stale window — mention any sends in the report so the operator is not surprised by channel messages.
