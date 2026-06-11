---
name: add-source
description: Add a secondary legacy RSS/news source to CryptoSentinel following the full validation procedure. Use only for RSS/news context, not for primary DEX price-move alerts.
argument-hint: "[feed-url] [tier 0|1|2]"
---

# Add Source - legacy RSS/news procedure

Adding a source is NOT just editing `config/sources.yaml`. This skill is for
secondary RSS/news context only. The primary product is DEX price-move alerts;
use `dexscreener-watchlist` for watched coin/pair movements.

## 1. Validate the feed first

```powershell
py -3 .claude/skills/add-source/scripts/validate_feed.py <feed-url>
```

The script encodes the project's hard-learned lessons (theblock.co 403, Blockworks 200-but-stale, DL News tombstone). Only proceed on `verdict: GOOD`. On `BAD`/`WARN`, report to the operator and stop — do not add a dead source.

## 2. Add to config/sources.yaml

- Pick a canonical `name` — it must be unique and is the EXACT key used for tier membership in step 3.
- Add `- name:` / `url:` under the matching tier comment block (Tier 0 fast wires / Tier 1 mainstream / Tier 2 supplementary). The comment blocks are documentation only — they do not set the tier.

## 3. Wire the tier (the gotcha)

Tier is decided by source-name sets hard-coded in TWO files that must stay in sync:

| Tier requested | Action |
|---|---|
| Tier 0 (fast wire) | Add the name to `FAST_SIGNAL_SOURCES` in `main.py` AND `agentic_runtime.py` (it is auto-included in TIER1 via the `*FAST_SIGNAL_SOURCES` splat) |
| Tier 1 | Add the name to `TIER1_SOURCES` in `main.py` AND `agentic_runtime.py` |
| Tier 2 | Nothing — any source not in those sets is Tier-2 by default (goes through 8B triage) |

Remember: Tier-0/Tier-1 bypass triage and always hit the 70B analyzer (recall-first), so promoting a noisy source to Tier-1 has a direct token cost.

## 4. Test a real parse of the new feed

```powershell
py -3 -c "from scrapers.generic_rss import scrape_all_feeds; arts = [a for a in scrape_all_feeds() if a.source == '<name>']; print(len(arts)); [print(a.published_at, a.title[:70]) for a in arts[:3]]"
```

(Adapt to the actual public function in `scrapers/generic_rss.py` if it differs.) Confirm: articles parse into the `Article` model, timestamps are timezone-aware UTC, titles are clean.

## 5. Run the unit suite

```powershell
py -3 -m pytest tests/unit -q
```

## 6. Report

Source name, URL, tier + files touched, validate_feed verdict, parse sample, test result. If the operator asked for Tier 1, mention the token-cost implication once.
