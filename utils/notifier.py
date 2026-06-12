"""
utils/notifier.py
=================
Telegram delivery của CryptoSentinel (v3 — DEX-only).

Gửi PairSignal dạng bảng giá DEXScreener-style. Không nhãn bullish/bearish,
không lời bình AI — chỉ số liệu thị trường + link chart.
"""

import os
import html
import time
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

from models.pair_signal import PairSignal

logger = logging.getLogger(__name__)
SLA_SECONDS = 120     # quan sát -> gửi quá 2 phút là vi phạm SLA tốc độ
MAX_429_RETRIES = 2   # số lần retry in-process khi Telegram trả 429
MAX_429_WAIT_S = 10   # trần chờ mỗi lần — giữ cadence pipeline không bị treo


def _is_main_channel(chat_id: str) -> bool:
    main_chat_id = (os.environ.get("CHAT_ID") or "").strip()
    return bool(chat_id and main_chat_id and chat_id == main_chat_id)


def _ops_telemetry_enabled() -> bool:
    """Cờ bật/tắt telemetry vận hành (admin alert + heartbeat). Mặc định tắt."""
    raw = (os.environ.get("ENABLE_OPS_TELEMETRY") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _post_to_telegram(
    token: str,
    chat_id: str,
    text: str,
    *,
    parse_mode: Optional[str] = None,
) -> bool:
    """Gửi một message tới Telegram Bot API, retry in-process khi 429."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    for attempt in range(1 + MAX_429_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            # 429: retry in-process theo retry_after thay vì đốt 1 attempt outbox
            if status == 429 and attempt < MAX_429_RETRIES:
                retry_after = MAX_429_WAIT_S
                try:
                    retry_after = int(e.response.json()["parameters"]["retry_after"])
                except Exception:
                    try:
                        retry_after = int(e.response.headers.get("Retry-After", MAX_429_WAIT_S))
                    except Exception:
                        pass
                wait_s = min(max(retry_after, 1), MAX_429_WAIT_S)
                logger.warning(
                    f"⚠️ Telegram 429 rate-limit — chờ {wait_s}s rồi thử lại "
                    f"({attempt + 1}/{MAX_429_RETRIES})..."
                )
                time.sleep(wait_s)
                continue
            logger.error(f"❌ Lỗi HTTP từ Telegram (status={status}): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi gửi Telegram: {e}")
            return False
    return False


def send_admin_alert(text: str) -> bool:
    """Gửi alert lỗi/chậm về kênh admin-only (ADMIN_CHAT_ID)."""
    if not _ops_telemetry_enabled():
        return False
    token = os.environ.get("BOT_TOKEN")
    admin_chat_id = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if not token or not admin_chat_id:
        return False
    if _is_main_channel(admin_chat_id):
        logger.warning("ADMIN_CHAT_ID trùng CHAT_ID (kênh chính). Bỏ qua admin alert.")
        return False
    return _post_to_telegram(token, admin_chat_id, text, parse_mode="HTML")


def send_signal(signal: PairSignal) -> bool:
    """
    Gửi một PairSignal:
    - Kênh chính (CHAT_ID): mọi signal vượt ngưỡng.
    - Kênh premium (PREMIUM_CHAT_ID, optional): chỉ move nóng (signal.is_hot).
    Trả về False chỉ khi kênh chính fail (premium fail chỉ log cảnh báo).
    """
    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    if not token or not chat_id:
        logger.error("CHƯA CẤU HÌNH BOT_TOKEN HOẶC CHAT_ID. Không thể gửi alert.")
        send_admin_alert("🚨 <b>Pipeline alert</b>: thiếu BOT_TOKEN hoặc CHAT_ID.")
        return False

    sent_at = datetime.now(timezone.utc)
    lag_seconds = max(0, int((sent_at - signal.observed_at).total_seconds()))

    message_text = signal.format_telegram_html()
    success = _post_to_telegram(token, chat_id, message_text, parse_mode="HTML")

    if success:
        logger.info(f"✅ Đã gửi alert: {signal.pair_label} {signal.change_pct:+.1f}% ({signal.horizon})")
        if lag_seconds > SLA_SECONDS:
            # WARNING log luôn ghi — SLA breach không tàng hình khi telemetry tắt
            logger.warning(
                f"⚠️ SLA_BREACH: lag={lag_seconds}s > {SLA_SECONDS}s | "
                f"{signal.pair_label} {signal.change_pct:+.1f}% {signal.horizon}"
            )
            send_admin_alert(
                f"⚠️ <b>SLA_BREACH</b>\n"
                f"{html.escape(signal.pair_label)} {signal.change_pct:+.1f}% {signal.horizon}\n"
                f"Lag={lag_seconds // 60}m{lag_seconds % 60:02d}s > SLA=2m"
            )
    else:
        send_admin_alert(
            f"🚨 <b>TG_SEND_FAIL</b>\n"
            f"{html.escape(signal.pair_label)} {signal.change_pct:+.1f}% {signal.horizon}"
        )

    # Kênh premium — chỉ move nóng, không ảnh hưởng kết quả trả về
    premium_chat_id = os.environ.get("PREMIUM_CHAT_ID", "").strip()
    if premium_chat_id and signal.is_hot:
        ok = _post_to_telegram(token, premium_chat_id, message_text, parse_mode="HTML")
        if ok:
            logger.info(f"✅ Đã gửi premium: {signal.pair_label}")
        else:
            logger.warning(f"⚠️ Premium channel fail cho {signal.id[:12]}. Kênh chính OK.")

    return success


def send_heartbeat(scanned: int, triggered: int, new: int,
                   db_errors: int, tg_errors: int,
                   duration_s: float,
                   tg_sent_ok: int = 0,
                   api_errors: int = 0,
                   pending_count: int = 0, failed_count: int = 0,
                   expired_count_60m: int = 0, oldest_pending_age_min: float = 0.0) -> bool:
    """
    Báo cáo tổng kết mỗi lần chạy về kênh ops (không phải kênh signal).

    Status:
      ✅ OK             — không lỗi
      ⚠️ N errors       — có lỗi nhưng pipeline không sập
      🛜 API degraded   — fetch DEXScreener fail: "quiet" lúc này KHÔNG đáng tin
      😴 quiet          — quét OK, không pair nào vượt ngưỡng (trạng thái lành mạnh)
    """
    if not _ops_telemetry_enabled():
        logger.info("Ops telemetry disabled: bỏ qua heartbeat Telegram.")
        return True

    token = os.environ.get("BOT_TOKEN")
    heartbeat_chat_id = os.environ.get("HEARTBEAT_CHAT_ID", "").strip()
    chat_id = heartbeat_chat_id or os.environ.get("ADMIN_CHAT_ID", "").strip()

    if not token:
        logger.warning("Không có BOT_TOKEN — bỏ qua heartbeat.")
        return False
    if not chat_id:
        logger.info("Không cấu hình HEARTBEAT_CHAT_ID/ADMIN_CHAT_ID — heartbeat chỉ ghi log.")
        return True
    if _is_main_channel(chat_id):
        logger.warning("HEARTBEAT chat trùng CHAT_ID (kênh chính). Bỏ qua để giữ kênh sạch.")
        return True

    total_errors = db_errors + tg_errors
    if total_errors > 0:
        status = f"⚠️ {total_errors} errors"
    elif api_errors > 0:
        # API fail mà vẫn 0 trigger thì KHÔNG được báo "quiet" — đó là mù, không phải im
        status = f"🛜 API degraded ({api_errors} fetch fail)"
    elif triggered == 0:
        status = "😴 quiet (no pair crossed thresholds)"
    else:
        status = "✅ OK"

    text = (
        f"<b>📊 CryptoSentinel Heartbeat</b> | {html.escape(status)}\n"
        f"├ Pairs scanned: {scanned} | Triggered: {triggered} | New: {new}\n"
        f"├ TG sent: {tg_sent_ok}\n"
        f"├ Outbox: pending={pending_count} | failed={failed_count} | "
        f"expired(60m)={expired_count_60m}\n"
        f"├ oldest_pending_age: {oldest_pending_age_min:.1f}m (cutoff 30m)\n"
        f"├ Errors — DB: {db_errors} | TG: {tg_errors} | API: {api_errors}\n"
        f"└ Duration: {duration_s:.1f}s"
    )

    success = _post_to_telegram(token, chat_id, text, parse_mode="HTML")
    if success:
        logger.info("✅ Heartbeat gửi thành công.")
    if total_errors > 0:
        send_admin_alert(
            f"🚨 <b>HEARTBEAT_ERRORS</b>\nDB={db_errors} | TG={tg_errors}\n"
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
# Smoke Test (LIVE-FIRE: gửi Telegram thật) — chạy: py -3 utils/notifier.py
# ===========================================================================
if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("LIVE TEST: gửi 1 alert giả lập tới CHAT_ID thật (cần BOT_TOKEN & CHAT_ID)")
    print("=" * 60)

    test_signal = PairSignal(
        chain_id="solana",
        dex_id="raydium",
        pair_address="EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
        base_symbol="WIF",
        quote_symbol="SOL",
        url="https://dexscreener.com/solana/EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
        horizon="h1",
        change_pct=12.4,
        price_usd=2.345,
        volume_usd=850_000,
        liquidity_usd=2_400_000,
        buys=221,
        sells=109,
        changes={"m5": 1.1, "h1": 12.4, "h6": 8.0, "h24": 15.3},
        dedup_key="dex:test:smoke:h1:UP:000000000000",
    )
    print(test_signal.format_telegram_html())
    print()
    if "--live" in sys.argv:
        ok = send_signal(test_signal)
        print("✅ Gửi thành công." if ok else "❌ Gửi thất bại — kiểm tra BOT_TOKEN/CHAT_ID.")
    else:
        print("(dry) Thêm --live để gửi thật.")
