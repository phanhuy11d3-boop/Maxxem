"""
Unit test cho bug timezone trong scrapers/generic_rss.py:
feedparser trả published_parsed là struct_time UTC; nếu convert bằng time.mktime
(diễn giải theo giờ local) thì trên máy UTC+7 mọi published_at bị lùi 7 tiếng,
khiến cửa sổ stale 30 phút lọc bỏ toàn bộ bài RSS một cách câm lặng.
Fix: calendar.timegm — kết quả phải độc lập timezone của host.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace

from scrapers import generic_rss


def _fake_feed(published_parsed):
    entry = {
        "link": "https://example.com/tz-test-article",
        "title": "Timezone regression test article",
        "summary": "Body",
    }
    entry_ns = SimpleNamespace(**entry, published_parsed=published_parsed)
    # scrape_feed dùng cả entry.get(...) lẫn hasattr(entry, ...)
    entry_ns.get = entry.get
    return SimpleNamespace(bozo=False, entries=[entry_ns])


def test_published_parsed_is_treated_as_utc(monkeypatch):
    # 2026-06-10 12:00:00 UTC — epoch chính xác, không phụ thuộc host TZ
    expected = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    struct = time.gmtime(expected.timestamp())

    monkeypatch.setattr(generic_rss.feedparser, "parse", lambda url: _fake_feed(struct))
    articles = generic_rss.scrape_feed({"name": "TZTest", "url": "https://example.com/feed"})

    assert len(articles) == 1
    art = articles[0]
    assert art.published_from_source is True
    # Bug cũ (time.mktime) trên máy UTC+7 sẽ cho 05:00 thay vì 12:00
    assert art.published_at == expected


def test_missing_published_falls_back_to_scrape_time(monkeypatch):
    feed = _fake_feed(None)
    monkeypatch.setattr(generic_rss.feedparser, "parse", lambda url: feed)

    before = datetime.now(timezone.utc)
    articles = generic_rss.scrape_feed({"name": "TZTest", "url": "https://example.com/feed"})
    after = datetime.now(timezone.utc)

    assert len(articles) == 1
    art = articles[0]
    assert art.published_from_source is False
    assert before <= art.published_at <= after
