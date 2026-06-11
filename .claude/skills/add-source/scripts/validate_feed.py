# -*- coding: utf-8 -*-
"""Validate an RSS/Atom feed before adding it to config/sources.yaml.

Usage: py -3 .claude/skills/add-source/scripts/validate_feed.py <feed-url>

Checks the lessons this project learned the hard way:
- theblock.co: HTTP 403 for bots (feed unusable despite existing)
- Blockworks: HTTP 200 but newest entry months old (tombstone/stale feed)
- DL News: feed still serving after the outlet shut down
So: a feed is only GOOD if it parses AND has a recent entry.
"""
import socket
import sys
from datetime import datetime, timezone

import feedparser

STALE_DAYS = 7
USER_AGENT = "Mozilla/5.0 (compatible; CryptoSentinelValidator/1.0)"


def main():
    if len(sys.argv) != 2:
        print("usage: validate_feed.py <feed-url>")
        sys.exit(1)
    url = sys.argv[1]
    socket.setdefaulttimeout(20)
    feed = feedparser.parse(url, agent=USER_AGENT)

    status = getattr(feed, "status", "n/a")
    print(f"url: {url}")
    print(f"http_status: {status}")
    print(f"bozo: {feed.bozo}" + (f" ({feed.bozo_exception})" if feed.bozo else ""))
    print(f"feed_title: {feed.feed.get('title', '<missing>')}")
    print(f"entries: {len(feed.entries)}")

    if not feed.entries:
        print("verdict: BAD - no entries (blocked, wrong URL, or empty feed)")
        sys.exit(2)

    newest = None
    missing_dates = 0
    for e in feed.entries:
        parsed = e.get("published_parsed") or e.get("updated_parsed")
        if parsed is None:
            missing_dates += 1
            continue
        dt = datetime(*parsed[:6], tzinfo=timezone.utc)
        if newest is None or dt > newest:
            newest = dt

    print(f"entries_missing_timestamp: {missing_dates}/{len(feed.entries)}"
          + (" (scraper will fall back to scrape-time, published_from_source=False)"
             if missing_dates else ""))

    for e in feed.entries[:3]:
        ts = e.get("published", e.get("updated", "<no date>"))
        print(f"  sample: [{ts}] {e.get('title', '<no title>')[:80]}")

    if newest is None:
        print("verdict: WARN - parses but NO entry has a timestamp; "
              "freshness cannot be verified, treat with caution")
        sys.exit(0)

    age_days = (datetime.now(timezone.utc) - newest).total_seconds() / 86400
    print(f"newest_entry_utc: {newest:%Y-%m-%d %H:%M} ({age_days:.1f} days old)")
    if age_days > STALE_DAYS:
        print(f"verdict: BAD - STALE feed (newest entry older than {STALE_DAYS} days; "
              "Blockworks/DL-News pattern: HTTP 200 does not mean alive)")
        sys.exit(2)
    print("verdict: GOOD - parses, has entries, and is fresh")


if __name__ == "__main__":
    main()
