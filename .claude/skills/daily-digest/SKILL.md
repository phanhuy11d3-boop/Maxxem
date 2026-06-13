---
name: daily-digest
description: Render and (optionally) send the CryptoSentinel 24h top-movers digest — a leaderboard of the biggest pair moves recorded in the signals table over the last day. Sending is LIVE-FIRE to Telegram. Use to preview the digest or trigger today's send manually.
disable-model-invocation: true
allowed-tools: Bash(py -3 scripts/daily_digest.py*)
---

# Daily Digest — 24h top-movers leaderboard

⚠️ **`--live` is LIVE-FIRE**: it sends a real Telegram message to
`DIGEST_CHAT_ID` (fallback `CHAT_ID`) and marks today as sent in
`storage/digest_state.json`. Name it as live-fire before running.

## Preview (dry — does NOT send)

```!
py -3 scripts/daily_digest.py
```

## How it works

- Ranks the strongest move per pair (by `|change_pct|`) from the last 24h of the
  `signals` table — **no API calls**, every number is replayed from stored
  alerts. No sentiment, no opinion (same contract as live alerts).
- **Does NOT go through the outbox.** A digest is a summary, not a time-sensitive
  price alert, so the 30-minute stale rule does not apply. Delivery is a direct
  send via `utils.notifier.send_digest`.
- **Idempotent:** one digest per UTC day. A second `--live` run the same day is
  skipped unless you pass `--force`. The marker lives in
  `storage/digest_state.json` and is written only after a successful send.

## To send today's digest (LIVE-FIRE)

State explicitly that this sends to Telegram, then:

```
py -3 scripts/daily_digest.py --live
```

Add `--force` only to re-send after an already-successful send today. The
scheduler can call the script directly once per day; this skill is for manual
preview / trigger.
