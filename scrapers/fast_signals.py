"""
scrapers/fast_signals.py
========================
Nguồn fast-signal kiểu KOL/news-wire qua API (optional).

Thiết kế:
- Không có API key => trả [] (không làm fail pipeline).
- Có API key nhưng endpoint lỗi => log warning và bỏ qua.
- Mọi record convert về Article để đi chung pipeline.
"""

from __future__ import annotations

import logging
import os
import re
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from models.article import Article

logger = logging.getLogger(__name__)

FAST_HTTP_TIMEOUT_S = 8
MAX_ITEMS_PER_API = 30
LOOKONCHAIN_URL = "https://www.lookonchain.com/feeds"


def _parse_dt(raw: Any) -> tuple[datetime, bool]:
    """
    Parse timestamp từ nhiều định dạng thường gặp API.
    Return (datetime_utc, from_source_flag).
    """
    if raw is None:
        return datetime.now(timezone.utc), False
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc), True
        except Exception:
            return datetime.now(timezone.utc), False
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return datetime.now(timezone.utc), False
        # ISO8601 common variants
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc), True
        except Exception:
            return datetime.now(timezone.utc), False
    return datetime.now(timezone.utc), False


def _safe_get_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    r = requests.get(url, headers=headers or {}, timeout=FAST_HTTP_TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def _safe_load_lookonchain_json(raw: str) -> Any:
    """
    Lookonchain /ashx/index.ashx đôi khi trả JSON có backslash escape không hợp lệ
    trong text content. Sửa nhẹ để parser không chết vì 1 ký tự trong bài.
    """
    cleaned = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", raw)
    return json.loads(cleaned, strict=False)


def _fetch_lookonchain() -> List[Article]:
    """
    Ingest Lookonchain từ endpoint nội bộ /ashx/index.ashx.

    Lookonchain không expose RSS hợp lệ, nhưng web app gọi endpoint này để load feed.
    Nếu endpoint đổi/hỏng, fallback sang HTML parser nhẹ bên dưới.
    """
    try:
        r = requests.get(
            "https://www.lookonchain.com/ashx/index.ashx",
            params={"page": 1, "count": MAX_ITEMS_PER_API},
            timeout=FAST_HTTP_TIMEOUT_S,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CryptoSentinel/1.0)",
                "Referer": LOOKONCHAIN_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        r.raise_for_status()
        data = _safe_load_lookonchain_json(r.text)
    except Exception as e:
        logger.warning("Fast-signal Lookonchain API unavailable, fallback HTML: %s", e)
        return _fetch_lookonchain_html()

    rows = data.get("content", []) if isinstance(data, dict) else []
    out: List[Article] = []
    for item in rows[:MAX_ITEMS_PER_API]:
        try:
            title = str(item.get("stitle") or "").strip().replace("\\'", "'")
            if len(title) < 5:
                continue
            iid = item.get("nnewflash_id")
            if not iid:
                continue
            # dcreate_time là giờ hiển thị của site; site dùng timezone gần UTC+8.
            raw_dt = item.get("dcreate_time")
            published_at, from_source = _parse_dt(raw_dt)
            if from_source and isinstance(raw_dt, str) and len(raw_dt) == 19:
                try:
                    published_at = datetime.strptime(raw_dt, "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=timezone(timedelta(hours=8))
                    ).astimezone(timezone.utc)
                except ValueError:
                    pass
            summary = re.sub(r"<[^>]+>", " ", str(item.get("sabstract") or item.get("scontent") or ""))
            summary = " ".join(summary.split())[:1000]
            out.append(
                Article(
                    url=f"https://www.lookonchain.com/feeds/{iid}",
                    title=title[:500],
                    source="Lookonchain",
                    published_at=published_at,
                    summary=summary,
                    published_from_source=from_source,
                )
            )
        except Exception:
            continue
    logger.info("Fast-signal Lookonchain API: %s bài.", len(out))
    return out


def _fetch_lookonchain_html() -> List[Article]:
    """Fallback HTML parser cho Lookonchain nếu endpoint nội bộ đổi/hỏng."""
    try:
        r = requests.get(
            LOOKONCHAIN_URL,
            timeout=FAST_HTTP_TIMEOUT_S,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CryptoSentinel/1.0)"},
        )
        r.raise_for_status()
        html = r.text
    except Exception as e:
        logger.warning("Fast-signal Lookonchain HTML unavailable: %s", e)
        return []

    # Match <a ... href="/feeds/123">title 2026.01.31 18:37:29</a>
    anchors = re.findall(
        r'<a[^>]+href=["\'](?P<href>/feeds/\d+)["\'][^>]*>(?P<body>.*?)</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    out: List[Article] = []
    seen: set[str] = set()
    for href, body in anchors[:MAX_ITEMS_PER_API * 2]:
        text = re.sub(r"<[^>]+>", "", body)
        text = " ".join(text.split())
        if not text:
            continue
        dt_match = re.search(r"(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})", text)
        published_at, from_source = _parse_dt(None)
        if dt_match:
            try:
                published_at = datetime.strptime(dt_match.group(1), "%Y.%m.%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                from_source = True
            except ValueError:
                pass
            title = text[: dt_match.start()].strip()
        else:
            title = text.strip()
        if len(title) < 5:
            continue
        link = urljoin(LOOKONCHAIN_URL, href)
        if link in seen:
            continue
        seen.add(link)
        try:
            out.append(
                Article(
                    url=link,
                    title=title[:500],
                    source="Lookonchain",
                    published_at=published_at,
                    summary=title,
                    published_from_source=from_source,
                )
            )
        except Exception:
            continue
        if len(out) >= MAX_ITEMS_PER_API:
            break
    logger.info("Fast-signal Lookonchain: %s bài.", len(out))
    return out


def _fetch_unusualwhales() -> List[Article]:
    """
    Ingest từ UnusualWhales API (optional, cần UW_API_KEY).
    Endpoint tham chiếu docs public: /api/alerts
    """
    api_key = (os.environ.get("UW_API_KEY") or "").strip()
    if not api_key:
        return []

    url = "https://api.unusualwhales.com/api/alerts?limit=30"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        data = _safe_get_json(url, headers=headers)
    except Exception as e:
        logger.warning("Fast-signal UW unavailable: %s", e)
        return []

    rows = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
    out: List[Article] = []
    for item in rows[:MAX_ITEMS_PER_API]:
        try:
            title = (
                str(item.get("title") or item.get("headline") or item.get("text") or "").strip()
            )
            if len(title) < 5:
                continue
            link = str(item.get("url") or item.get("link") or "").strip()
            if not link:
                # fallback deterministic URL để dedup được qua id-hash
                iid = item.get("id") or item.get("_id") or title[:32]
                link = f"https://www.unusualwhales.com/alerts/{iid}"
            published_at, from_source = _parse_dt(
                item.get("created_at") or item.get("timestamp") or item.get("time")
            )
            summary = str(item.get("description") or item.get("body") or item.get("text") or "")[:1000]
            out.append(
                Article(
                    url=link,
                    title=title,
                    source="UnusualWhales",
                    published_at=published_at,
                    summary=summary,
                    published_from_source=from_source,
                )
            )
        except Exception:
            continue
    logger.info("Fast-signal UnusualWhales: %s bài.", len(out))
    return out


def _fetch_arkham() -> List[Article]:
    """
    Ingest từ Arkham Alerts API (optional, cần ARKHAM_API_KEY).
    Endpoint có thể thay đổi theo gói API; fail sẽ bỏ qua an toàn.
    """
    api_key = (os.environ.get("ARKHAM_API_KEY") or "").strip()
    if not api_key:
        return []

    # Placeholder endpoint theo pattern docs public; nếu không hợp lệ sẽ catch warning.
    url = "https://intel.arkm.com/api/v1/alerts?limit=30"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        data = _safe_get_json(url, headers=headers)
    except Exception as e:
        logger.warning("Fast-signal Arkham unavailable: %s", e)
        return []

    rows = data if isinstance(data, list) else data.get("results", []) if isinstance(data, dict) else []
    out: List[Article] = []
    for item in rows[:MAX_ITEMS_PER_API]:
        try:
            title = str(item.get("title") or item.get("name") or item.get("message") or "").strip()
            if len(title) < 5:
                continue
            link = str(item.get("url") or item.get("link") or "").strip()
            if not link:
                iid = item.get("id") or title[:32]
                link = f"https://intel.arkm.com/explorer/alerts/{iid}"
            published_at, from_source = _parse_dt(
                item.get("created_at") or item.get("timestamp") or item.get("time")
            )
            summary = str(item.get("description") or item.get("message") or "")[:1000]
            out.append(
                Article(
                    url=link,
                    title=title,
                    source="Arkham Alerts",
                    published_at=published_at,
                    summary=summary,
                    published_from_source=from_source,
                )
            )
        except Exception:
            continue
    logger.info("Fast-signal Arkham: %s bài.", len(out))
    return out


def fetch_fast_signals() -> List[Article]:
    """
    Aggregate các nguồn API fast-signal.
    """
    out: List[Article] = []
    out.extend(_fetch_lookonchain())
    out.extend(_fetch_unusualwhales())
    out.extend(_fetch_arkham())
    return out

