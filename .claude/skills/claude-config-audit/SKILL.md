---
name: claude-config-audit
description: Validate project Claude skills and subagents against the checked Claude Code format. Use after editing .claude/skills or .claude/agents, or when a skill references missing scripts or a subagent preloads a missing skill.
allowed-tools: Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/run_claude_config_audit.py*)
context: fork
agent: ops-manager
shell: powershell
---

# Claude Config Audit

Run the colocated validator:

```!
py -3 ${CLAUDE_SKILL_DIR}/scripts/run_claude_config_audit.py
```

Fix every FAIL before committing `.claude` changes. The validator is read-only
and checks frontmatter, script references, and subagent skill preloads.

