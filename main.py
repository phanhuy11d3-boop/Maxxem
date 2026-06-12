"""
main.py
=======
Orchestrator của CryptoSentinel v3 — DEX-only price-move alerts.

Pipeline mỗi vòng (cadence 1 phút, hai ca local + GH Actions chung DB):

  1. expire stale + dispatch outbox backlog (alert cũ còn pending/failed)
  2. scan DEXScreener watchlist → PairSignal vượt ngưỡng
  3. insert batch (dedup theo cooldown bucket ngay tại cổng DB)
  4. dispatch outbox → Telegram
  5. heartbeat (chỉ khi ENABLE_OPS_TELEMETRY bật)

Không RSS. Không LLM. Mọi con số trong alert đến từ DEXScreener API.
"""

import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from storage.postgres import (
    init_db, insert_signals_batch, get_tg_dispatch_queue,
    claim_tg_send_slot, mark_tg_attempt, expire_stale_tg_queue, get_outbox_kpis,
)
from scrapers.dexscreener import load_config, scan_watchlist
from utils.notifier import send_signal, send_heartbeat, send_admin_alert

# Cấu hình logging tập trung một lần duy nhất — module con kế thừa getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STALE_WINDOW_MINUTES = 30
MAX_TG_ATTEMPTS = 3

STATE_FILE = Path(__file__).parent / "storage" / "state.json"


def _update_state(db_errors: int, tg_errors: int, api_errors: int = 0) -> None:
    """Ghi trạng thái pipeline vào state.json sau mỗi lần chạy (ghi đè sạch — không vác key mồ côi)."""
    try:
        state = {
            "last_run": datetime.now(timezone.utc).isoformat(),
            "current_phase": "idle",
            "system_status": "degraded" if (db_errors + tg_errors + api_errors) > 0 else "healthy",
            "errors": {"db": db_errors, "telegram": tg_errors, "api": api_errors},
        }
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Không thể ghi state.json: {e}")


def _dispatch_tg_queue() -> Tuple[int, int]:
    """
    Outbox dispatcher:
      - expire stale (> cửa sổ tươi) trước khi gửi — alert giá muộn là alert sai
      - gửi queue pending/failed, claim slot chống 2 ca gửi trùng

    Returns: (sent_ok_count, tg_errors_count)
    """
    sent_ok = 0
    tg_errors = 0

    expired = expire_stale_tg_queue(max_age_minutes=STALE_WINDOW_MINUTES)
    if expired:
        logger.warning("Outbox expired stale: %s alert.", expired)
        send_admin_alert(f"⏭️ <b>TG_EXPIRED</b>\nExpired stale alerts: {expired}")

    queue = get_tg_dispatch_queue(
        max_age_minutes=STALE_WINDOW_MINUTES, max_attempts=MAX_TG_ATTEMPTS
    )
    if not queue:
        return sent_ok, tg_errors

    logger.info("Dispatch TG queue: %s alert pending/failed.", len(queue))
    for signal in queue:
        # 2 ca (local + GH) cùng quét outbox — chỉ kẻ claim được mới gửi.
        if not claim_tg_send_slot(signal.id):
            continue
        sent = send_signal(signal)
        mark_tg_attempt(signal.id, success=sent, error=None if sent else "send_failed")
        if sent:
            sent_ok += 1
        else:
            tg_errors += 1
    return sent_ok, tg_errors


def run_pipeline() -> None:
    """Pipeline tuyến tính v3 — heartbeat được đảm bảo bởi try...finally."""
    start_time = time.monotonic()
    logger.info("=== Bắt đầu chạy pipeline CryptoSentinel v3 (DEX-only) ===")

    db_errors = 0
    tg_errors = 0
    api_errors = 0
    scanned_count = 0
    triggered_count = 0
    new_count = 0
    tg_sent_ok_total = 0

    # Phase 1: init_db — nếu fail, báo và thoát ngay
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Không thể khởi tạo DB. Dừng pipeline: {e}")
        send_admin_alert(f"🚨 <b>PIPELINE_INIT_DB_FAIL</b>\n{e!s}")
        send_heartbeat(
            scanned=0, triggered=0, new=0,
            db_errors=1, tg_errors=0,
            duration_s=time.monotonic() - start_time,
        )
        return

    try:
        # Phase 2: Dispatch backlog cũ trước khi quét mới
        c_ok, c_tg = _dispatch_tg_queue()
        tg_sent_ok_total += c_ok
        tg_errors += c_tg

        # Phase 3: Quét DEXScreener watchlist
        scanned_count = len(load_config().get("watchlist") or [])
        logger.info("3. Quét DEXScreener watchlist (%s pair)...", scanned_count)
        signals, api_errors = scan_watchlist()
        triggered_count = len(signals)
        if api_errors:
            # No-silent-quiet: API sập phải kêu, không được giả dạng thị trường im
            logger.error("DEXScreener API degraded: %s fetch fail vòng này.", api_errors)
            send_admin_alert(
                f"🛜 <b>DEX_API_DEGRADED</b>\n{api_errors} fetch fail — "
                f"trạng thái quiet vòng này KHÔNG đáng tin."
            )

        # Phase 4: Insert + dedup (cooldown bucket nằm trong dedup_key)
        if signals:
            new_count, batch_db_errors = insert_signals_batch(signals)
            db_errors += batch_db_errors
            logger.info("4. %s/%s signal mới (sau dedup cooldown).", new_count, triggered_count)
        else:
            logger.info("4. Không pair nào vượt ngưỡng — quiet là trạng thái lành mạnh.")

        # Phase 5: Dispatch các signal vừa enqueue
        c_ok, c_tg = _dispatch_tg_queue()
        tg_sent_ok_total += c_ok
        tg_errors += c_tg

    except Exception as e:
        logger.critical(f"Pipeline crash không mong đợi: {e}", exc_info=True)
        send_admin_alert(f"🚨 <b>PIPELINE_CRASH</b>\n{e!s}")
        db_errors += 1

    finally:
        duration = time.monotonic() - start_time
        kpi = get_outbox_kpis(max_age_minutes=STALE_WINDOW_MINUTES)
        logger.info(
            f"=== Pipeline Hoàn Tất | "
            f"Scanned: {scanned_count} | Triggered: {triggered_count} | Mới: {new_count} | "
            f"TG OK: {tg_sent_ok_total} | Lỗi DB/TG/API: {db_errors}/{tg_errors}/{api_errors} | "
            f"Thời gian: {duration:.1f}s ==="
        )
        send_heartbeat(
            scanned=scanned_count,
            triggered=triggered_count,
            new=new_count,
            db_errors=db_errors,
            tg_errors=tg_errors,
            duration_s=duration,
            tg_sent_ok=tg_sent_ok_total,
            api_errors=api_errors,
            pending_count=kpi["pending_count"],
            failed_count=kpi["failed_count"],
            expired_count_60m=kpi["expired_count_60m"],
            oldest_pending_age_min=kpi["oldest_pending_age_min"],
        )
        _update_state(db_errors=db_errors, tg_errors=tg_errors, api_errors=api_errors)


def main() -> None:
    run_pipeline()


if __name__ == "__main__":
    main()
