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


def _build_premium_message(article: Article) -> str:
    """
    Bản tin đầy đủ cho kênh Premium: giữ nguyên format HTML + thêm signal box.
    Chỉ gọi khi article.is_actionable == True.
    """
    base = article.format_telegram_html()
    extras: list[str] = []
    if article.urgency in ("breaking", "important"):
        extras.append(f"⚡ Urgency: <b>{html.escape(article.urgency.upper())}</b>")
    if article.affected_tokens:
        tokens_str = " ".join(f"<code>{html.escape(t)}</code>" for t in article.affected_tokens)
        extras.append(f"🎯 Tokens: {tokens_str}")
    if article.key_takeaway:
        kt = html.escape(article.key_takeaway)
        extras.append(f'💡 Signal: <i>"{kt}"</i>')
    if extras:
        signal_block = "\n─── <b>PREMIUM SIGNAL</b> ───\n" + "\n".join(extras)
        return base + "\n" + signal_block
    return base


def send_telegram(article: Article) -> bool:
    """
    Gửi tin nhắn Telegram cho một bài báo.
    - Free channel (CHAT_ID): tất cả actionable articles.
    - Premium channel (PREMIUM_CHAT_ID, optional): breaking/important articles với full signal.
    Chỉ trả về False nếu Free channel fail (Premium failure chỉ log cảnh báo).
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
        logger.info(f"✅ Đã gửi Telegram (free): {article.title[:40]}...")

    # Kênh Premium — tuỳ chọn, không ảnh hưởng kết quả trả về của hàm này
    premium_chat_id = os.environ.get("PREMIUM_CHAT_ID", "").strip()
    if premium_chat_id and article.urgency in ("breaking", "important"):
        time.sleep(1)
        premium_text = _build_premium_message(article)
        ok = _post_to_telegram(token, premium_chat_id, premium_text, parse_mode="HTML")
        if ok:
            logger.info(f"✅ Đã gửi Telegram (premium): {article.title[:40]}...")
        else:
            logger.warning(f"⚠️ Premium channel fail cho {article.id[:12]}. Free channel OK.")

    return success


def send_heartbeat(scraped: int, new: int, ai_processed: int,
                   db_errors: int, llm_errors: int, tg_errors: int,
                   duration_s: float,
                   actionable: int = 0, tg_sent_ok: int = 0) -> bool:
    """
    Gửi báo cáo tổng kết pipeline sau mỗi lần chạy.
    Cho phép USER biết pipeline đang sống hay chết mà không cần vào GitHub Actions.

    Status icon:
      ✅ = Tất cả OK (không có lỗi nào)
      ⚠️ = Có lỗi NHƯNG pipeline không sập
      🔇 = "Silent run" — không lỗi nhưng cũng không gửi tin nào (cần xem prompt/triage)

    Bug đã sửa (2026-05-07): trước đây heartbeat chỉ in ``tg_errors`` (đếm fail).
    Khi pipeline có 0 fail VÀ 0 attempt thì cũng hiện "TG: 0", che mất việc bot
    im lặng vì LLM gắn nhãn neutral hết. Thêm ``actionable``/``tg_sent_ok`` để
    USER nhìn 1 phát ra ngay trạng thái thật.
    """
    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")

    if not token or not chat_id:
        logger.warning("Không có BOT_TOKEN/CHAT_ID — bỏ qua heartbeat.")
        return False

    total_errors = db_errors + llm_errors + tg_errors
    if total_errors > 0:
        status = f"⚠️ {total_errors} errors"
    elif ai_processed > 0 and tg_sent_ok == 0 and actionable == 0:
        status = "🔇 silent (no actionable)"
    else:
        status = "✅ OK"
    safe_status = html.escape(status)

    text = (
        f"<b>📊 CryptoSentinel Heartbeat</b> | {safe_status}\n"
        f"├ Scraped: {scraped} bài | Mới: {new}\n"
        f"├ AI processed: {ai_processed} | Actionable: {actionable} | TG sent: {tg_sent_ok}\n"
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
