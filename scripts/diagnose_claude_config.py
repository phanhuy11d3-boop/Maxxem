"""Validate project Claude skills/subagents for drift.

Read-only. Checks the parts that tend to silently rot:
- every SKILL.md has required frontmatter
- project skills do not use stale/non-doc frontmatter aliases
- Python script references in skills point to real files
- subagents have required frontmatter and preload existing skills
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"
AGENTS_DIR = ROOT / ".claude" / "agents"

SKILL_KEYS = {
    "name",
    "description",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "hooks",
    "paths",
    "shell",
}
AGENT_KEYS = {
    "name",
    "description",
    "tools",
    "disallowedTools",
    "model",
    "permissionMode",
    "maxTurns",
    "skills",
    "mcpServers",
    "hooks",
    "memory",
    "background",
    "effort",
    "isolation",
    "color",
    "initialPrompt",
}
STALE_SKILL_KEYS = {"argument-hint"}


def _frontmatter(path: Path) -> tuple[dict[str, str], list[str], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, [], text
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, [], text

    raw = lines[1:end]
    fields: dict[str, str] = {}
    for line in raw:
        if not line or line.startswith(" ") or line.startswith("-"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields, raw, "\n".join(lines[end + 1 :])


def _script_refs(path: Path, body: str) -> list[Path]:
    refs: list[Path] = []
    for match in re.finditer(r"(?:py\s+-3|python)\s+([^`\r\n ]+\.py)", body):
        raw = match.group(1).strip().strip('"').strip("'")
        raw = raw.replace("${CLAUDE_SKILL_DIR}", str(path.parent))
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        refs.append(candidate)
    return refs


def _agent_skill_refs(raw_frontmatter: list[str]) -> list[str]:
    refs: list[str] = []
    in_skills = False
    for line in raw_frontmatter:
        if re.match(r"^\S[^:]*:", line):
            in_skills = line.strip() == "skills:"
            continue
        if in_skills:
            m = re.match(r"\s*-\s*([A-Za-z0-9_-]+)\s*$", line)
            if m:
                refs.append(m.group(1))
    return refs


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    issues: list[str] = []
    skill_names: set[str] = set()

    for skill in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        fields, _raw, body = _frontmatter(skill)
        rel = skill.relative_to(ROOT)
        name = fields.get("name")
        if not name:
            issues.append(f"{rel}: missing frontmatter name")
        else:
            skill_names.add(name)
            if name != skill.parent.name:
                issues.append(f"{rel}: name '{name}' does not match folder '{skill.parent.name}'")
        if not fields.get("description"):
            issues.append(f"{rel}: missing description")
        for key in fields:
            if key in STALE_SKILL_KEYS:
                issues.append(f"{rel}: stale key '{key}', use Claude docs key 'arguments'")
            elif key not in SKILL_KEYS:
                issues.append(f"{rel}: unknown skill frontmatter key '{key}'")
        for ref in _script_refs(skill, body):
            if not ref.exists():
                issues.append(f"{rel}: referenced script missing: {ref.relative_to(ROOT)}")

    for agent in sorted(AGENTS_DIR.glob("*.md")):
        fields, raw, _body = _frontmatter(agent)
        rel = agent.relative_to(ROOT)
        name = fields.get("name")
        if not name:
            issues.append(f"{rel}: missing frontmatter name")
        elif not re.fullmatch(r"[a-z0-9-]+", name):
            issues.append(f"{rel}: invalid agent name '{name}'")
        if not fields.get("description"):
            issues.append(f"{rel}: missing description")
        for key in fields:
            if key not in AGENT_KEYS:
                issues.append(f"{rel}: unknown subagent frontmatter key '{key}'")
        for ref in _agent_skill_refs(raw):
            if ref not in skill_names:
                issues.append(f"{rel}: preloads missing skill '{ref}'")

    print("=" * 72)
    print("CLAUDE CONFIG DIAGNOSIS (read-only)")
    print("=" * 72)
    if issues:
        for issue in issues:
            print(f"FAIL {issue}")
        print(f"\nResult: FAIL ({len(issues)} issue(s))")
        return 1
    print(f"Skills: {len(skill_names)}")
    print(f"Subagents: {len(list(AGENTS_DIR.glob('*.md')))}")
    print("\nResult: PASS (skills/subagents match checked Claude format)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
