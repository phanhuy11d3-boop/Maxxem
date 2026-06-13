# Agent And Skill Map

## Agents

| Agent | Ownership |
|---|---|
| `source-resilience-engineer` | source adapters, source health, freshness |
| `ingestion-scout` | DEX scanner and watchlist ingestion |
| `signal-analyst` | thresholds, gates, scoring calibration |
| `alert-rate-auditor` | alert volume, backpressure, dispatch priority |
| `db-auditor` | signals table, outbox, schema safety |
| `notifier-broadcaster` | Telegram delivery and format |
| `ops-manager` | schedules, preflight, pipeline orchestration |
| `realtime-feed-researcher` | read-only realtime source evaluation |
| `market-data-archivist` | optional snapshots and retention |

## Skills

| Skill | Use |
|---|---|
| `health-sweep` | full read-only source -> delivery sweep |
| `source-health-audit` | source freshness and degraded quiet |
| `outbox-audit` | Telegram outbox state machine and send-lag audit |
| `telegram-render-audit` | backend signal fields vs Telegram HTML alignment |
| `claude-config-audit` | validate `.claude/skills` and `.claude/agents` format |
| `realtime-shadow` | inspect shadow/canary realtime feeds |
| `source-integration-plan` | plan a new source before implementation |
| `threshold-backtest` | stored-alert threshold pressure analysis |
| `alert-rate-audit` | queue pressure and noisy pair/horizon audit |
| `incident-postmortem` | structured incident review |

Read-only skills and agents must not write DB state or send Telegram. Operational
skills own colocated scripts under their skill directory; SKILL.md should invoke
those entrypoints instead of depending on ad-hoc shell snippets.
