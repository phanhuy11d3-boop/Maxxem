"""
agentic_runtime.py
==================
Runtime orchestration cho chế độ agentic opt-in của CryptoSentinel.

Thiết kế "balanced":
- Legacy pipeline vẫn là default production.
- Agentic chỉ chạy khi gọi `python main.py --agentic`.
- Nếu mapping agent/skill lỗi hoặc stage fail nghiêm trọng, caller fallback về legacy.
- Runtime không đọc file playbook từ disk. Agent/skill registry là map tĩnh đã kiểm soát
  để tránh crash khi tài liệu vận hành bị thiếu hoặc thay đổi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from models.article import Article, MarketImpact
from processors.insight_extractor import (
    BatchOutcome,
    analyze_articles_batch,
    get_llm_client,
    triage_articles,
)
from scrapers.generic_rss import scrape_all_feeds
from storage.postgres import (
    expire_stale_tg_queue,
    get_tg_dispatch_queue,
    claim_tg_send_slot,
    get_unprocessed,
    increment_retry,
    init_db,
    mark_processed_with_tg,
    mark_tg_attempt,
    upsert_articles_batch,
)
from utils.notifier import send_admin_alert, send_telegram

logger = logging.getLogger(__name__)
LOW_CONF_SENTIMENT_ABS_THRESHOLD = 0.25
FAST_SIGNAL_SOURCES = {"Watcher.Guru", "Lookonchain", "UnusualWhales", "Arkham Alerts"}
TIER1_SOURCES = {
    "Blockworks", "CoinDesk", "Cointelegraph", "Unchained Crypto",
    "CryptoSlate", "SEC Press Releases",
    *FAST_SIGNAL_SOURCES,
}

DEFAULT_AGENT_SKILL_MAP = {
    "scout": "scout-ingestion-skill",
    "analyst": "crypto-insight-alpha-skill",
    "auditor": "audit-security-skill",
    "broadcaster": "broadcasting-delivery-skill",
}

@dataclass
class PipelineStats:
    scraped_count: int = 0
    new_count: int = 0
    ai_processed: int = 0
    db_errors: int = 0
    llm_errors: int = 0
    tg_errors: int = 0
    warnings: int = 0
    actionable: int = 0
    tg_sent_ok: int = 0


@dataclass
class RuntimeContext:
    registry: Dict[str, str]
    actionable_articles: List[Article] = field(default_factory=list)
    actionable_ids: set[str] = field(default_factory=set)

    def push_actionable(self, article: Article) -> None:
        if article.id not in self.actionable_ids:
            self.actionable_articles.append(article)
            self.actionable_ids.add(article.id)


def load_agent_skill_registry(_base_dir: object | None = None) -> Dict[str, str]:
    """
    Trả về registry tĩnh cho runtime.

    `_base_dir` được giữ để không phá caller/test cũ, nhưng runtime không đọc file
    playbook nữa. Tài liệu vận hành chỉ dành cho người/AI đọc.
    """
    return dict(DEFAULT_AGENT_SKILL_MAP)


def _stage_scout(ctx: RuntimeContext, stats: PipelineStats) -> None:
    logger.info("[Scout] Ingestion từ RSS feeds...")
    articles = scrape_all_feeds()
    stats.scraped_count = len(articles)

    new_count, db_errors = upsert_articles_batch(articles)
    stats.new_count += new_count
    stats.db_errors += db_errors
    logger.info("[Scout] Scraped=%s | New=%s", stats.scraped_count, stats.new_count)


def _stage_analyst(ctx: RuntimeContext, stats: PipelineStats, max_batch_size: int) -> None:
    logger.info("[Analyst] Lấy queue chưa xử lý...")
    unprocessed = get_unprocessed()
    unprocessed.sort(
        key=lambda a: (
            0 if a.source in TIER1_SOURCES else 1,
            -a.scraped_at.timestamp(),
        )
    )
    total_unprocessed = len(unprocessed)
    if total_unprocessed == 0:
        logger.info("[Analyst] Không có bài cần phân tích.")
        return

    client = get_llm_client()
    if not client:
        logger.error("[Analyst] Không có LLM client, tăng retry cho queue.")
        stats.llm_errors += total_unprocessed
        for article in unprocessed:
            increment_retry(article.id)
        return

    logger.info("[Analyst] Tổng queue=%s | batch_size=%s", total_unprocessed, max_batch_size)
    num_chunks = (total_unprocessed + max_batch_size - 1) // max_batch_size

    for idx, chunk_start in enumerate(range(0, total_unprocessed, max_batch_size), 1):
        chunk = unprocessed[chunk_start : chunk_start + max_batch_size]
        logger.info("[Analyst] Chunk %s/%s (%s bài)", idx, num_chunks, len(chunk))

        tier1 = [a for a in chunk if a.source in TIER1_SOURCES]
        tier2 = [a for a in chunk if a.source not in TIER1_SOURCES]
        low_conf_ids: set[str] = set()
        high_impact: List[Article] = list(tier1)

        if tier2:
            triage_map = triage_articles(tier2, client)
            for article in tier2:
                high_impact.append(article)
                if not triage_map.get(article.id, True):
                    low_conf_ids.add(article.id)

        if not high_impact:
            continue

        outcome, missing = analyze_articles_batch(high_impact, client)

        if outcome == BatchOutcome.STRUCTURAL_FAIL:
            stats.llm_errors += len(high_impact)
            send_admin_alert(
                "🚨 <b>LLM_STRUCTURAL_FAIL</b>\n"
                f"[Agentic] Chunk size={len(high_impact)}. Prompt cần xem lại."
            )
            continue

        if outcome == BatchOutcome.TRANSIENT_FAIL:
            stats.llm_errors += len(high_impact)
            send_admin_alert(
                f"⚠️ <b>LLM_TRANSIENT_FAIL</b>\n[Agentic] Chunk size={len(high_impact)}"
            )
            for article in high_impact:
                increment_retry(article.id)
            continue

        for article in high_impact:
            article.low_confidence = bool(getattr(article, "low_confidence", False)) or (
                article.id in low_conf_ids
                or (
                    article.sentiment is not None
                    and abs(article.sentiment) < LOW_CONF_SENTIMENT_ABS_THRESHOLD
                )
            )

            # Outbox state machine:
            # - actionable -> enqueue pending (tg_status='pending', attempts=0)
            # - neutral    -> no tg state
            if article.is_actionable:
                mark_processed_with_tg(
                    article_id=article.id,
                    sentiment=article.sentiment,
                    market_impact=article.market_impact or MarketImpact.NEUTRAL,
                    key_takeaway=article.key_takeaway,
                    narrative_tag=article.narrative_tag,
                    affected_tokens=article.affected_tokens,
                    urgency=article.urgency,
                    low_confidence=article.low_confidence,
                    tg_sent=None,
                    tg_status="pending",
                    tg_attempts=0,
                )
                ctx.push_actionable(article)
            else:
                mark_processed_with_tg(
                    article_id=article.id,
                    sentiment=article.sentiment,
                    market_impact=article.market_impact or MarketImpact.NEUTRAL,
                    key_takeaway=article.key_takeaway,
                    narrative_tag=article.narrative_tag,
                    affected_tokens=article.affected_tokens,
                    urgency=article.urgency,
                    low_confidence=article.low_confidence,
                    tg_sent=None,
                    tg_status=None,
                )
            stats.ai_processed += 1

        if missing:
            send_admin_alert(
                f"⚠️ <b>LLM_MISSING_RESULTS</b>\n[Agentic] {len(missing)}/"
                f"{len(high_impact)} bị 70B bỏ quên — đã đóng low_conf."
            )

    logger.info("[Analyst] AI processed=%s | Actionable=%s", stats.ai_processed, len(ctx.actionable_articles))


def _stage_auditor(ctx: RuntimeContext, stats: PipelineStats) -> None:
    logger.info("[Auditor] Gatekeeping dữ liệu actionable trước khi broadcast...")
    reviewed: List[Article] = []
    for article in ctx.actionable_articles:
        if article.market_impact not in (MarketImpact.BULLISH, MarketImpact.BEARISH):
            stats.warnings += 1
            continue
        if not article.key_takeaway:
            stats.warnings += 1
            continue
        reviewed.append(article)

    filtered = len(ctx.actionable_articles) - len(reviewed)
    if filtered > 0:
        logger.warning("[Auditor] Đã lọc %s bài không đạt gate tối thiểu.", filtered)
    ctx.actionable_articles = reviewed
    ctx.actionable_ids = {a.id for a in reviewed}


def _stage_broadcaster(ctx: RuntimeContext, stats: PipelineStats) -> None:
    logger.info("[Broadcaster] Dispatch queue pending/failed trong cửa sổ 30 phút...")
    expired = expire_stale_tg_queue(max_age_minutes=30)
    if expired:
        send_admin_alert(f"⏭️ <b>TG_EXPIRED</b>\n[Agentic] expired stale: {expired}")

    failed_articles = get_tg_dispatch_queue(max_age_minutes=30, max_attempts=3)
    seen_ids = set()
    for article in failed_articles:
        seen_ids.add(article.id)
        # 2 ca (local + GH) cùng quét outbox — chỉ kẻ claim được mới gửi.
        if not claim_tg_send_slot(article.id):
            continue
        stats.actionable += 1
        sent = send_telegram(article)
        mark_tg_attempt(article.id, sent, None if sent else "send_failed")
        if sent:
            stats.tg_sent_ok += 1
        else:
            stats.tg_errors += 1

    logger.info("[Broadcaster] Gửi các actionable mới từ analyst...")
    for article in ctx.actionable_articles:
        if article.id in seen_ids:
            # Đã được retry từ dispatch queue ở vòng trên — tránh gửi double.
            continue
        if not claim_tg_send_slot(article.id):
            continue
        stats.actionable += 1
        sent = send_telegram(article)
        mark_tg_attempt(article.id, sent, None if sent else "send_failed")
        if sent:
            stats.tg_sent_ok += 1
        else:
            stats.tg_errors += 1


def run_agentic_pipeline(max_batch_size: int = 20, base_dir: object | None = None) -> PipelineStats:
    """
    Chạy pipeline agentic theo chuỗi:
    Scout -> Analyst -> Auditor -> Broadcaster.
    """
    registry = load_agent_skill_registry(base_dir)
    logger.info("[Agentic] Skill registry: %s", registry)
    ctx = RuntimeContext(registry=registry)
    stats = PipelineStats()

    init_db()

    expected_skills = DEFAULT_AGENT_SKILL_MAP
    if registry.get("scout") != expected_skills["scout"]:
        logger.warning("[Agentic] Scout skill '%s' chưa có handler riêng, dùng handler mặc định.", registry.get("scout"))
    _stage_scout(ctx, stats)

    if registry.get("analyst") != expected_skills["analyst"]:
        logger.warning("[Agentic] Analyst skill '%s' chưa có handler riêng, dùng handler mặc định.", registry.get("analyst"))
    _stage_analyst(ctx, stats, max_batch_size=max_batch_size)

    if registry.get("auditor") != expected_skills["auditor"]:
        logger.warning("[Agentic] Auditor skill '%s' chưa có handler riêng, dùng handler mặc định.", registry.get("auditor"))
    _stage_auditor(ctx, stats)

    if registry.get("broadcaster") != expected_skills["broadcaster"]:
        logger.warning(
            "[Agentic] Broadcaster skill '%s' chưa có handler riêng, dùng handler mặc định.",
            registry.get("broadcaster"),
        )
    _stage_broadcaster(ctx, stats)

    return stats
