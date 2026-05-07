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
    analyze_articles_batch,
    get_groq_client,
    triage_articles,
)
from scrapers.generic_rss import scrape_all_feeds
from storage.postgres import (
    get_tg_failed,
    get_unprocessed,
    increment_retry,
    init_db,
    mark_processed,
    mark_tg_sent,
    upsert_article,
)
from utils.notifier import send_telegram

logger = logging.getLogger(__name__)

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

    for article in articles:
        result = upsert_article(article)
        if result is None:
            stats.db_errors += 1
        elif result:
            stats.new_count += 1
    logger.info("[Scout] Scraped=%s | New=%s", stats.scraped_count, stats.new_count)


def _stage_analyst(ctx: RuntimeContext, stats: PipelineStats, max_batch_size: int) -> None:
    logger.info("[Analyst] Lấy queue chưa xử lý...")
    unprocessed = get_unprocessed()
    total_unprocessed = len(unprocessed)
    if total_unprocessed == 0:
        logger.info("[Analyst] Không có bài cần phân tích.")
        return

    client = get_groq_client()
    if not client:
        logger.error("[Analyst] Không có Groq client, tăng retry cho queue.")
        stats.llm_errors += total_unprocessed
        for article in unprocessed:
            increment_retry(article.id)
        return

    logger.info("[Analyst] Tổng queue=%s | batch_size=%s", total_unprocessed, max_batch_size)
    num_chunks = (total_unprocessed + max_batch_size - 1) // max_batch_size

    for idx, chunk_start in enumerate(range(0, total_unprocessed, max_batch_size), 1):
        chunk = unprocessed[chunk_start : chunk_start + max_batch_size]
        logger.info("[Analyst] Chunk %s/%s (%s bài)", idx, num_chunks, len(chunk))

        triage_results = triage_articles(chunk, client)
        n_triage = min(len(triage_results), len(chunk))

        high_impact: List[Article] = []
        for i in range(n_triage):
            article = chunk[i]
            if triage_results[i]:
                high_impact.append(article)
            else:
                mark_processed(
                    article.id,
                    0.0,
                    MarketImpact.NEUTRAL,
                    "Routine news - skipped deep analysis.",
                )
                stats.ai_processed += 1

        # Fallback: thiếu nhãn triage thì vẫn cho qua phân tích
        for i in range(n_triage, len(chunk)):
            high_impact.append(chunk[i])

        if not high_impact:
            continue

        success = analyze_articles_batch(high_impact, client)
        if not success:
            stats.llm_errors += len(high_impact)
            for article in high_impact:
                increment_retry(article.id)
            continue

        for article in high_impact:
            if not article.processed:
                stats.llm_errors += 1
                increment_retry(article.id)
                continue

            mark_processed(
                article_id=article.id,
                sentiment=article.sentiment,
                market_impact=article.market_impact or MarketImpact.NEUTRAL,
                key_takeaway=article.key_takeaway,
                narrative_tag=article.narrative_tag,
                affected_tokens=article.affected_tokens,
                urgency=article.urgency,
            )
            stats.ai_processed += 1

            if article.is_actionable:
                ctx.push_actionable(article)

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
    logger.info("[Broadcaster] Retry các bài TG cần (re)gửi từ trước...")
    failed_articles = get_tg_failed()
    for article in failed_articles:
        stats.actionable += 1
        sent = send_telegram(article)
        mark_tg_sent(article.id, sent)
        if sent:
            stats.tg_sent_ok += 1
        else:
            stats.tg_errors += 1

    logger.info("[Broadcaster] Gửi các actionable mới từ analyst...")
    for article in ctx.actionable_articles:
        stats.actionable += 1
        sent = send_telegram(article)
        mark_tg_sent(article.id, sent)
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
