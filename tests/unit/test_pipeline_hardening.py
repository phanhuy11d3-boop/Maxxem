"""
Unit tests cho 4 vector hardening:
  - 3a: triage trả Dict[id->bool] có anti-miss khi LLM bóp méo idx.
  - 3b: bài bị 70B "bỏ quên" được mark processed+low_confidence, KHÔNG retry-tax.
  - 3c: classify_exception phân biệt transient vs structural.
  - 3d: format_telegram_html in Published/Sent/Lag ICT.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from processors import insight_extractor as ix
from models.article import Article, MarketImpact


def _make_article(idx: int, source: str = "Cointelegraph") -> Article:
    return Article(
        url=f"https://example.com/post-{idx}",
        title=f"Test article {idx} about market",
        source=source,
        published_at=datetime.now(timezone.utc),
        summary="Some summary",
    )


class _FakeChat:
    def __init__(self, payload: str):
        self._payload = payload

    def create(self, **_kwargs):
        choice = SimpleNamespace(message=SimpleNamespace(content=self._payload))
        return SimpleNamespace(choices=[choice])


class _FakeClient:
    def __init__(self, payload: str):
        self.chat = SimpleNamespace(completions=_FakeChat(payload))


# ---------- Vector 3a ----------
def test_triage_returns_dict_keyed_by_article_id():
    arts = [_make_article(i) for i in range(3)]
    payload = json.dumps({"results": [
        {"idx": 0, "high_impact": True},
        {"idx": 1, "high_impact": False},
        {"idx": 2, "high_impact": True},
    ]})
    out = ix.triage_articles(arts, _FakeClient(payload))
    assert set(out.keys()) == {a.id for a in arts}
    assert out[arts[0].id] is True
    assert out[arts[1].id] is False
    assert out[arts[2].id] is True


def test_triage_anti_miss_when_too_many_missing_idx():
    """Nếu LLM trả thiếu > TRIAGE_ANTI_MISS_RATIO (30%) → all True."""
    arts = [_make_article(i) for i in range(5)]
    payload = json.dumps({"results": [{"idx": 0, "high_impact": False}]})
    out = ix.triage_articles(arts, _FakeClient(payload))
    assert all(out.values()), "Anti-miss policy: phải coi tất cả là high_impact"


def test_triage_handles_exception_with_all_true_fallback():
    arts = [_make_article(i) for i in range(2)]

    class _Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: (_ for _ in ()).throw(RuntimeError("network"))
        ))

    out = ix.triage_articles(arts, _Boom())
    assert out == {a.id: True for a in arts}


# ---------- Vector 3b ----------
def test_analyze_batch_marks_missing_articles_as_low_conf_processed():
    arts = [_make_article(i) for i in range(2)]
    payload = json.dumps({"results": [
        {
            "id": arts[0].id,
            "sentiment": 0.6,
            "market_impact": "bullish",
            "key_takeaway": "BTC breakout",
            "narrative_tag": "BTC_ETF",
            "affected_tokens": ["$BTC"],
            "urgency": "important",
        }
        # cố ý bỏ qua arts[1]
    ]})
    outcome, missing = ix.analyze_articles_batch(arts, _FakeClient(payload))
    assert outcome == ix.BatchOutcome.OK
    assert missing == [arts[1]]
    # bài missing phải được auto-close, KHÔNG để caller tăng retry
    assert arts[1].processed is True
    assert arts[1].low_confidence is True
    assert arts[1].market_impact == MarketImpact.NEUTRAL


# ---------- Vector 3c ----------
def test_classify_structural_error_does_not_retry():
    err = json.JSONDecodeError("bad", "", 0)
    assert ix._classify_exception(err) == ix.BatchOutcome.STRUCTURAL_FAIL


def test_classify_transient_error_keyword():
    err = RuntimeError("Rate limit exceeded (429)")
    assert ix._classify_exception(err) == ix.BatchOutcome.TRANSIENT_FAIL


def test_analyze_batch_structural_fail_short_circuits():
    arts = [_make_article(i) for i in range(2)]
    payload = "this is not json {{"
    outcome, missing = ix.analyze_articles_batch(arts, _FakeClient(payload))
    assert outcome == ix.BatchOutcome.STRUCTURAL_FAIL
    assert missing == []


# ---------- Vector 3d ----------
def test_format_telegram_html_includes_published_sent_lag_ict():
    pub = datetime.now(timezone.utc) - timedelta(minutes=2)
    art = Article(
        url="https://example.com/btc-up",
        title="BTC moves higher",
        source="CoinDesk",
        published_at=pub,
        sentiment=0.7,
        market_impact=MarketImpact.BULLISH,
        key_takeaway="ETF inflows hit record",
        processed=True,
    )
    sent_at = pub + timedelta(minutes=2)
    msg = art.format_telegram_html(sent_at=sent_at)
    assert "Source time (ICT):" in msg
    assert "Sent:" in msg
    assert "Lag:" in msg


def test_format_telegram_hides_source_time_if_unknown():
    pub = datetime.now(timezone.utc) - timedelta(minutes=1)
    art = Article(
        url="https://example.com/no-source-time",
        title="No source time sample",
        source="UnknownFeed",
        published_at=pub,
        published_from_source=False,
        sentiment=0.2,
        market_impact=MarketImpact.BULLISH,
        key_takeaway="sample",
        processed=True,
    )
    msg = art.format_telegram_html(sent_at=pub + timedelta(minutes=1))
    assert "Source time (ICT):" not in msg


def test_format_telegram_html_marks_low_confidence():
    art = Article(
        url="https://example.com/x",
        title="Borderline news",
        source="Decrypt",
        published_at=datetime.now(timezone.utc),
        sentiment=0.1,
        market_impact=MarketImpact.BULLISH,
        key_takeaway="Some hint",
        processed=True,
        low_confidence=True,
    )
    msg = art.format_telegram_html()
    assert "[?]" in msg
    assert "Confidence: [?] low" in msg
