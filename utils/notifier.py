"""
utils/notifier.py
=================
Mô-đun thông báo của CryptoSentinel.
Chịu trách nhiệm gửi tín hiệu (Bullish/Bearish) tới Telegram.
"""

import os
import html
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

from models.article import Article

logger = logging.getLogger(__name__)
SLA_SECONDS = 120


def _is_main_channel(chat_id: str) -> bool:
    main_chat_id = (os.environ.get("CHAT_ID") or "").strip()
    return bool(chat_id and main_chat_id and chat_id == main_chat_id)


def _ops_telemetry_enabled() -> bool:
    """
    Cờ bật/tắt telemetry vận hành (admin alert + heartbeat).
    Mặc định tắt để giữ kênh Telegram sạch khi cần quan sát thuần signal.
    """
    raw = (os.environ.get("ENABLE_OPS_TELEMETRY") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}

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


def _reference_ts(article: Article) -> datetime:
    """Ưu tiên published_at; fallback scraped_at nếu dữ liệu published lỗi."""
    try:
        if article.published_at and article.published_at.tzinfo is not None:
            return article.published_at
    except Exception:
        pass
    return article.scraped_at


def _lag_seconds(article: Article, sent_at: datetime) -> int:
    ref = _reference_ts(article)
    return max(0, int((sent_at - ref).total_seconds()))


def send_admin_alert(text: str) -> bool:
    """Gửi alert lỗi/chậm về kênh admin-only (ADMIN_CHAT_ID)."""
    if not _ops_telemetry_enabled():
        return False
    token = os.environ.get("BOT_TOKEN")
    admin_chat_id = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if not token or not admin_chat_id:
        return False
    if _is_main_channel(admin_chat_id):
        logger.warning("ADMIN_CHAT_ID trùng CHAT_ID (kênh chính). Bỏ qua admin alert để tránh spam UI.")
        return False
    return _post_to_telegram(token, admin_chat_id, text, parse_mode="HTML")


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
        send_admin_alert("🚨 <b>Pipeline alert</b>: thiếu BOT_TOKEN hoặc CHAT_ID, không thể gửi tín hiệu.")
        return False

    sent_at = datetime.now(timezone.utc)
    lag_seconds = _lag_seconds(article, sent_at)

    message_text = article.format_telegram_html(sent_at=sent_at)

    success = _post_to_telegram(token, chat_id, message_text, parse_mode="HTML")
    if success:
        logger.info(f"✅ Đã gửi Telegram (free): {article.title[:40]}...")
        if lag_seconds > SLA_SECONDS:
            send_admin_alert(
                f"⚠️ <b>SLA_BREACH</b>\n"
                f"{html.escape(article.source)} | {html.escape(article.title[:120])}\n"
                f"Lag={lag_seconds//60}m{lag_seconds%60:02d}s > SLA=2m"
            )
    else:
        send_admin_alert(
            f"🚨 <b>TG_SEND_FAIL</b>\n"
            f"{html.escape(article.source)} | {html.escape(article.title[:120])}"
        )

    # Kênh Premium — tuỳ chọn, không ảnh hưởng kết quả trả về của hàm này
    premium_chat_id = os.environ.get("PREMIUM_CHAT_ID", "").strip()
    if premium_chat_id and article.urgency in ("breaking", "important"):
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
                   actionable: int = 0, tg_sent_ok: int = 0,
                   pending_count: int = 0, failed_count: int = 0,
                   expired_count_60m: int = 0, oldest_pending_age_min: float = 0.0) -> bool:
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
    if not _ops_telemetry_enabled():
        logger.info("Ops telemetry disabled: bỏ qua heartbeat Telegram.")
        return True

    token = os.environ.get("BOT_TOKEN")
    # Không spam kênh cộng đồng. Heartbeat chỉ đi kênh riêng nếu có cấu hình.
    # Ưu tiên HEARTBEAT_CHAT_ID, fallback ADMIN_CHAT_ID.
    heartbeat_chat_id = os.environ.get("HEARTBEAT_CHAT_ID", "").strip()
    chat_id = heartbeat_chat_id or os.environ.get("ADMIN_CHAT_ID", "").strip()

    if not token:
        logger.warning("Không có BOT_TOKEN — bỏ qua heartbeat.")
        return False
    if not chat_id:
        logger.info("Không cấu hình HEARTBEAT_CHAT_ID/ADMIN_CHAT_ID — heartbeat chỉ ghi log nội bộ.")
        return True
    if _is_main_channel(chat_id):
        logger.warning(
            "HEARTBEAT_CHAT_ID/ADMIN_CHAT_ID trùng CHAT_ID (kênh chính). "
            "Bỏ qua heartbeat để giữ UI sạch."
        )
        return True

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
        f"├ Outbox: pending={pending_count} | failed={failed_count} | "
        f"expired(60m)={expired_count_60m}\n"
        f"├ oldest_pending_age: {oldest_pending_age_min:.1f}m (cutoff 30m)\n"
        f"├ Errors — DB: {db_errors} | LLM: {llm_errors} | TG: {tg_errors}\n"
        f"└ Duration: {duration_s:.1f}s"
    )

    success = _post_to_telegram(token, chat_id, text, parse_mode="HTML")
    if success:
        logger.info("✅ Heartbeat gửi thành công.")
    if total_errors > 0:
        send_admin_alert(
            f"🚨 <b>HEARTBEAT_ERRORS</b>\n"
            f"DB={db_errors} | LLM={llm_errors} | TG={tg_errors}\n"
            f"Duration={duration_s:.1f}s"
        )
    if oldest_pending_age_min >= 24:
        send_admin_alert(
            f"⚠️ <b>OUTBOX_RISK</b>\n"
            f"oldest_pending_age={oldest_pending_age_min:.1f}m (cutoff 30m)\n"
            f"pending={pending_count} failed={failed_count} expired(60m)={expired_count_60m}"
        )
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
