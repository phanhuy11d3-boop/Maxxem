"""
scrapers/generic_rss.py
=======================
Mô-đun cào tin tức từ các nguồn RSS feed.
Thực hiện đọc nguồn từ config/sources.yaml, parse với feedparser,
và trả về danh sách các đối tượng Article.
"""

import yaml
import feedparser
import logging
from typing import List
from datetime import datetime, timezone
import calendar
from email.utils import parsedate_to_datetime
from pydantic import ValidationError
import socket

from models.article import Article
from scrapers.dexscreener import fetch_dexscreener_alerts
from scrapers.fast_signals import fetch_fast_signals

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_FEED = 30  # Giới hạn bài / feed / lần chạy — tránh flood DB khi feed tích tụ
FEED_TIMEOUT_S = 10      # Timeout mạng cho mỗi feed (giây)

def load_sources(config_path: str = "config/sources.yaml") -> List[dict]:
    """Tải danh sách các RSS feeds từ file cấu hình."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config.get("feeds", [])
    except FileNotFoundError:
        logger.error(f"Không tìm thấy file cấu hình tại {config_path}")
        return []
    except yaml.YAMLError as e:
        logger.error(f"Lỗi parse YAML file {config_path}: {e}")
        return []

def scrape_feed(source: dict) -> List[Article]:
    """Cào tin từ một feed duy nhất và trả về danh sách Article."""
    name = source.get("name")
    url = source.get("url")
    if not name or not url:
        logger.warning(f"Source thiếu name hoặc url: {source}")
        return []

    logger.info(f"Đang lấy dữ liệu từ {name} ({url})...")

    # Timeout: 1 feed chết không được làm treo cả pipeline
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(FEED_TIMEOUT_S)
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.error(f"❌ Feed {name} không phản hồi trong {FEED_TIMEOUT_S}s: {e}")
        return []
    finally:
        socket.setdefaulttimeout(old_timeout)

    if feed.bozo and not feed.entries:
        logger.warning(f"⚠️ Feed {name} trả về lỗi cấu trúc và không có entries: {feed.bozo_exception}")
        return []
    
    articles = []
    for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
        try:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            
            # Xử lý published_at
            published_at = None
            published_from_source = True
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                # published_parsed là struct_time UTC; calendar.timegm giữ nguyên UTC,
                # còn time.mktime sẽ diễn giải nhầm theo giờ local (lệch -7h trên máy ICT)
                published_at = datetime.fromtimestamp(calendar.timegm(entry.published_parsed), timezone.utc)
            elif hasattr(entry, "published") and entry.published:
                try:
                    published_at = parsedate_to_datetime(entry.published)
                except (TypeError, ValueError):
                    pass
            
            if not published_at:
                published_at = datetime.now(timezone.utc)
                published_from_source = False

            summary = entry.get("summary", "")
            
            # Pydantic validation
            article = Article(
                url=link,
                title=title,
                source=name,
                published_at=published_at,
                summary=summary,
                published_from_source=published_from_source,
            )
            articles.append(article)
            
        except ValidationError as e:
            # Lỗi nếu data vi phạm luật trong models/article.py
            logger.warning(f"Bỏ qua bài không hợp lệ từ {name}: {title[:30]}... Lỗi: {e.errors()[0]['msg']}")
            continue
        except Exception as e:
            logger.error(f"Lỗi không xác định khi parse bài từ {name}: {e}")
            continue

    logger.info(f"Hoàn thành {name}: lấy được {len(articles)} bài hợp lệ.")
    return articles

def scrape_all_feeds(config_path: str = "config/sources.yaml") -> List[Article]:
    """Cào tất cả các feeds được định nghĩa trong file cấu hình."""
    sources = load_sources(config_path)
    all_articles = []

    # DEXScreener price-move alerts are deterministic, already-actionable
    # Article objects. They run before RSS because the product focus is direct
    # coin/pair movement, not generic news volume.
    try:
        all_articles.extend(fetch_dexscreener_alerts())
    except Exception as e:
        logger.warning(f"DEXScreener ingestion skipped due to error: {e}")
    
    for source in sources:
        articles = scrape_feed(source)
        all_articles.extend(articles)

    # Fast-signal APIs (optional): chỉ chạy khi có API keys, không làm fail pipeline.
    try:
        all_articles.extend(fetch_fast_signals())
    except Exception as e:
        logger.warning(f"Fast-signal ingestion skipped due to error: {e}")

    return all_articles

# ===========================================================================
# Smoke Test — chạy: python scrapers/generic_rss.py
# ===========================================================================
if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    print("=" * 60)
    print("TEST: Chạy Scraper với Cointelegraph (Mock)")
    print("=" * 60)
    
    mock_sources = [
        {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"}
    ]
    
    test_articles = []
    for source in mock_sources:
        test_articles.extend(scrape_feed(source))
        
    print("=" * 60)
    print(f"Tổng số bài lấy được: {len(test_articles)}")
    if test_articles:
        print("\nThông tin bài mới nhất:")
        print(f"  Tiêu đề     : {test_articles[0].title}")
        print(f"  Nguồn       : {test_articles[0].source}")
        print(f"  URL         : {test_articles[0].url}")
        print(f"  ID (SHA-256): {test_articles[0].id}")
        print(f"  Published At: {test_articles[0].published_at}")
