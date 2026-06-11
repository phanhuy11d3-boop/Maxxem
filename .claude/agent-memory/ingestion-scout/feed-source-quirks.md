---
name: feed-source-quirks
description: Per-source RSS/API health quirks — dead/stale feeds (DL News closed, Blockworks editorial stale, The Block 403) and known-good baselines
metadata:
  type: project
---

Per-source ingestion quirks (last verified 2026-06-11):

- **DL News — DEAD, removed from sources.yaml 2026-06-10.** Publication permanently closed; final article "DL News is closing" published 2026-05-07. Feed URL still returns 200 with 30 stale items (tombstone). Do not re-add.
- **Blockworks — STALE since 2026-01-07.** Feed wrapper regenerates (feed-level `updated` is current) but newest *entry* is 2026-01-07. Site pivoted to "data and software platform"; `blockworks.co` redirects to `blockworks.com`; `/news` and `/news/feed` return 403 to non-browser UAs. Kept in config (200 OK, may resume) but contributes zero fresh items. It was the designated Tier-1 replacement for The Block, so Tier-1 currently has a coverage gap — operator needs to pick a real replacement.
- **The Block (theblock.co)** — returns HTTP 403 to all RSS scrapers since 2026-05 (server-side bot blocking, no durable bypass). Already documented in sources.yaml comment.
- **Lookonchain** — no valid RSS; ingest via internal `/ashx/index.ashx` endpoint (handled in `scrapers/fast_signals.py`). Healthy as of 2026-06-10 (~1.9s, 30 items, timestamps UTC+8 converted correctly). JSON sometimes has invalid backslash escapes — cleaner already in code.
- **CoinGape — FLAKY (feed-side malformed XML).** 2026-06-11: 10 bozo failures ("mismatched tag") across ~87 cycles, incl. one 36-min outage 15:28–15:59 local where the *same* byte position `<unknown>:95:3992` repeated 8 cycles (bad article cached in their feed) — self-healed at 16:04 without intervention. Scraper degrades gracefully (0 articles, no crash). Don't escalate unless an outage exceeds ~1h.
- **Unchained Crypto — occasional 10s read timeouts** (3–4/day observed 2026-06-11) plus one not-well-formed response. Recovers next cycle; server is slow, not dead.
- **Known-good baseline (2026-06-10):** Watcher.Guru, CoinDesk, Cointelegraph, Unchained Crypto, Decrypt, The Defiant, Bitcoin Magazine, Protos all OK; latency 0.8–3.0s; all timestamps tz-aware UTC from source; zero Article validation failures; no future-dated timestamps. Feeds capped at 10 items server-side: Watcher.Guru, Unchained, Bitcoin Magazine, Protos (normal, not a defect).

**Why:** avoids re-diagnosing dead/stale feeds on every health sweep and gives a latency/volume baseline to compare against.
**How to apply:** during health checks, treat the above baselines as expected; flag deviations only. Before recommending re-adding DL News or trusting Blockworks for Tier-1 coverage, re-verify the publisher's status first.
