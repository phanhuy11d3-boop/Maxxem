"""
utils/notifier.py
=================
Mô-đun thông báo của CryptoSentinel.
Chịu trách nhiệm gửi tín hiệu (Bullish/Bearish) tới Telegram.
"""

import os
import html
import time
import logging
import requests
from typing import Optional

from models.article import Article

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _post_to_telegram(
    token: str,
    chat_id: str,
    text: str,
    *,
    parse_mode: Optional[str] = None,
) -> bool:
    """
    Helper nội bộ: gửi một message tới Telegram API.
    ``parse_mode`` dùng chuẩn Bot API (vd. ``HTML``, ``Markdown``). Để trống → văn bản thuần.

    Prefer ``HTML`` + ``html.escape`` cho nội dung có tiêu đề RSS — Markdown legacy dễ vỡ vì ``_*[]()``.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ Lỗi HTTP từ Telegram: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Lỗi gửi Telegram: {e}")
        return False


def send_telegram(article: Article) -> bool:
    """
    Gửi tin nhắn Telegram cho một bài báo.
    Chỉ gửi nếu bài báo là 'actionable' (Bullish/Bearish).
    """
    if not article.is_actionable:
        logger.debug(f"Bỏ qua bài báo trung lập (Neutral): {article.id}")
        return False

    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")

    if not token or not chat_id:
        logger.error("CHƯA CẤU HÌNH BOT_TOKEN HOẶC CHAT_ID. Không thể gửi tin nhắn.")
        return False

    message_text = article.format_telegram_html()

    # FinOps Rate Limit: Ngăn chặn Telegram chặn bot nếu gửi quá nhanh
    time.sleep(2)

    success = _post_to_telegram(token, chat_id, message_text, parse_mode="HTML")
    if success:
        logger.info(f"✅ Đã gửi Telegram thành công: {article.title[:40]}...")
    return success


def send_heartbeat(scraped: int, new: int, ai_processed: int,
                   db_errors: int, llm_errors: int, tg_errors: int,
                   duration_s: float) -> bool:
    """
    Gửi báo cáo tổng kết pipeline sau mỗi lần chạy.
    Cho phép USER biết pipeline đang sống hay chết mà không cần vào GitHub Actions.

    Status icon:
      ✅ = Tất cả OK (không có lỗi nào)
      ⚠️ = Có lỗi nhưng pipeline không sập
    """
    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")

    if not token or not chat_id:
        logger.warning("Không có BOT_TOKEN/CHAT_ID — bỏ qua heartbeat.")
        return False

    total_errors = db_errors + llm_errors + tg_errors
    status = "✅ OK" if total_errors == 0 else f"⚠️ {total_errors} errors"
    safe_status = html.escape(status)

    text = (
        f"<b>📊 CryptoSentinel Heartbeat</b> | {safe_status}\n"
        f"├ Scraped: {scraped} bài | Mới: {new}\n"
        f"├ AI processed: {ai_processed}\n"
        f"├ Errors — DB: {db_errors} | LLM: {llm_errors} | TG: {tg_errors}\n"
        f"└ Duration: {duration_s:.1f}s"
    )

    success = _post_to_telegram(token, chat_id, text, parse_mode="HTML")
    if success:
        logger.info("✅ Heartbeat gửi thành công.")
    return success

# ===========================================================================
# Smoke Test — chạy: python utils/notifier.py
# ===========================================================================
if __name__ == "__main__":
    from datetime import datetime, timezone
    from models.article import MarketImpact
    import sys
    
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    print("=" * 60)
    print("TEST: Chạy Telegram Notifier (Yêu cầu có BOT_TOKEN & CHAT_ID)")
    print("=" * 60)
    
    # Tạo một bài báo giả lập Bullish để test
    test_article = Article(
        url="https://theblock.co/test-notifier",
        title="Institutional Investors Accumulate $5B in Bitcoin",
        source="The Block",
        published_at=datetime.now(timezone.utc),
        summary="Major hedge funds increase their exposure to BTC spot ETFs.",
        sentiment=0.85,
        market_impact=MarketImpact.BULLISH,
        key_takeaway="Institutional demand hits record highs with $5B in net inflows.",
        processed=True
    )
    
    print(f"Đang gửi bài: {test_article.title}")
    success = send_telegram(test_article)
    
    if success:
        print("\n✅ Test gửi Telegram thành công.")
    else:
        print("\n❌ Gửi thất bại. Kiểm tra TOKEN/CHAT_ID hoặc bài báo có phải Bullish/Bearish không.")
