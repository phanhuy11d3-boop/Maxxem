"""
processors/insight_extractor.py
===============================
Mô-đun tương tác với LLM qua endpoint OpenAI-compatible (cấu hình bằng env).
Tối ưu hóa Token FinOps: Tiered LLM (triage -> deep analysis) & Batch Processing.

Trading-grade hardening (2026-05-07):
  - Triage giờ trả Dict[id -> bool] thay vì List[bool] thuần →
    chống hoán vị thứ tự khi LLM bóp méo (Vector 3a).
  - Anti-miss: thiếu/sai >30% nhãn → coi tất cả là high_impact, không bỏ sót.
  - Batch analysis phân biệt transient (rate-limit/network) và structural
    (JSON malformed) → chỉ retry transient (Vector 3c).
  - Bài bị LLM "bỏ quên" trong response không bị retry-tax; được đánh dấu
    processed=True + low_confidence để PM thấy nhưng không phá queue (Vector 3b).
"""

import os
import json
import time
import logging
from typing import Optional, Dict, List, Tuple

from openai import OpenAI
from models.article import Article, MarketImpact, normalize_market_impact

logger = logging.getLogger(__name__)

# LLM endpoint OpenAI-compatible, cấu hình qua env:
#   LLM_API_KEY  — API key (bắt buộc)
#   LLM_BASE_URL — base URL của gateway, vd. http://localhost:20128/v1
#   LLM_MODEL    — model dùng chung cho cả triage lẫn deep analysis
#   LLM_MODEL_FAST / LLM_MODEL_POWER — override riêng nếu muốn tier hoá lại
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gc/gemini-3-pro-preview")
FAST_MODEL = os.environ.get("LLM_MODEL_FAST", DEFAULT_MODEL)
POWER_MODEL = os.environ.get("LLM_MODEL_POWER", DEFAULT_MODEL)
# Model dự phòng (LLM_MODEL_BACKUP): primary lỗi (429 capacity / JSON hỏng) → tự đổi
# sang model này ngay, không chờ backoff, rồi mới rơi về anti-miss / transient handling.
# Để trống = tắt fallback, giữ hành vi retry cùng model như cũ.
BACKUP_MODEL = os.environ.get("LLM_MODEL_BACKUP", "")

# Rescue threshold: nếu LLM trả market_impact="neutral" nhưng |sentiment| đủ mạnh,
# suy ngược ra direction. Tránh trường hợp model nhả "neutral" + sentiment=0.7 vô lý.
SENTIMENT_RESCUE_THRESHOLD = 0.4

# Anti-miss: nếu triage trả thiếu/sai > ngưỡng này thì coi như mọi bài đều high_impact.
TRIAGE_ANTI_MISS_RATIO = 0.30

# Batch analysis: số lần thử lại với lỗi transient (rate limit / network).
ANALYZE_TRANSIENT_RETRIES = 1
ANALYZE_TRANSIENT_BACKOFF_S = 2.0


# --- PROMPTS ---
TRIAGE_PROMPT = """You are a crypto news triage filter. Decide for each item whether it is
"high_impact" (market moving — hacks, major funding>$25M, regulation, ETF, exchange events,
liquidation cascades, macro/Fed, listing/delisting, exploit, mainnet launch, treasury moves)
or "low_impact" (routine PR, opinion, fluff, off-topic news).

ANTI-MISS RULE: when uncertain, prefer "high_impact". A false high_impact costs one extra LLM
call; a false low_impact silences a real signal.

INPUT FORMAT: a JSON array of objects, each {"idx": <int>, "title": "..."}.
OUTPUT FORMAT (strict JSON, no prose):
{"results": [{"idx": <same int>, "high_impact": true|false}, ...]}
The "idx" MUST be copied byte-for-byte from input. Length of "results" MUST equal length
of input. Do NOT shorten or paraphrase idx values."""

SYSTEM_PROMPT_BATCH = """You are CryptoSentinel: skeptical, data-driven. Use ONLY title/summary provided.

CRITICAL OUTPUT CONTRACT (read carefully — non-conforming responses are auto-discarded):
- "id" MUST be copied byte-for-byte from the input id. Do NOT shorten, hash, or rename.
- "market_impact" MUST be EXACTLY one of these three lowercase strings:
      "bullish"   (price-up signal)
      "bearish"   (price-down signal)
      "neutral"   (no clear directional signal OR insufficient data)
  DO NOT use "positive", "negative", "up", "down", "pump", "dump", "long", "short", "mixed", "uncertain", or anything else.
- Default to "neutral" when uncertain — but if title clearly indicates direction (e.g. "Bitcoin surges 10%", "Coinbase cuts 14% workforce", "exchange hacked", "ETF sees record inflows"), commit to "bullish" or "bearish".

Analysis rules:
- Do not invent numbers or facts absent from input. If totally insufficient → sentiment 0.0, market_impact "neutral".
- key_takeaway: max 20 words, dry tone; quote a concrete number (%, $, count) from input when possible.
- Forbidden in key_takeaway: revolutionary, game-changer, groundbreaking, massive, huge, moon, explode, skyrocket.
- narrative_tag: pick ONE from [AI, RWA, DePIN, BTC_ETF, Regulation, Hack, Macro, Other].
- affected_tokens: up to 3 tokens as $SYMBOL (e.g. ["$BTC","$ETH"]); [] if unclear.
- urgency: "breaking" for hacks/bans/exchange failures; "important" for funding>$50M/mainnet/major partnership; "context" otherwise.

Return ONE JSON object (no markdown, no prose), shape:
{"results": [{"id": "...", "sentiment": 0.0, "market_impact": "neutral", "key_takeaway": "...", "narrative_tag": "Other", "affected_tokens": [], "urgency": "context"}]}
Length of "results" MUST equal length of input."""


def get_llm_client() -> Optional[OpenAI]:
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    if not api_key or not base_url:
        logger.error("Chưa cấu hình LLM_API_KEY / LLM_BASE_URL.")
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


# ===========================================================================
# Vector 3a fix: Triage trả Dict[article_id -> bool], match theo idx có kiểm chứng
# ===========================================================================

def triage_articles(articles: List[Article], client: OpenAI) -> Dict[str, bool]:
    """
    Trả về dict {article.id: high_impact?}. Anti-miss:
      - Bài LLM bỏ quên (idx không có trong response) → True (cho qua 70B).
      - Nếu missing/invalid > TRIAGE_ANTI_MISS_RATIO của batch → coi cả batch là True.
      - Nếu LLM throw exception → mọi bài True.
    Caller chỉ cần `result.get(article.id, True)` — không cần dùng index.
    """
    if not articles:
        return {}

    items = [{"idx": i, "title": a.title} for i, a in enumerate(articles)]
    fallback_all_true = {a.id: True for a in articles}

    models_to_try = [FAST_MODEL]
    if BACKUP_MODEL and BACKUP_MODEL != FAST_MODEL:
        models_to_try.append(BACKUP_MODEL)

    data = None
    for model_name in models_to_try:
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": TRIAGE_PROMPT},
                    {"role": "user", "content": json.dumps(items)},
                ],
                model=model_name,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
            break
        except Exception as e:
            logger.error("Triage error với model %s: %s", model_name, e)
    if data is None:
        logger.error("Triage hết model khả dụng → fallback anti-miss (all high_impact).")
        return fallback_all_true

    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        logger.warning("Triage response không có 'results' list → anti-miss all True.")
        return fallback_all_true

    by_idx: Dict[int, bool] = {}
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r["idx"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(articles):
            by_idx[idx] = bool(r.get("high_impact", True))

    missing = sum(1 for i in range(len(articles)) if i not in by_idx)
    if missing / max(1, len(articles)) > TRIAGE_ANTI_MISS_RATIO:
        logger.warning(
            "Triage missing %d/%d (>%.0f%%) → anti-miss: treat ALL as high_impact.",
            missing, len(articles), TRIAGE_ANTI_MISS_RATIO * 100,
        )
        return fallback_all_true

    return {a.id: by_idx.get(i, True) for i, a in enumerate(articles)}


# ===========================================================================
# Vector 3b + 3c fix: Batch analysis với phân biệt lỗi + per-article missing flag
# ===========================================================================

class _BatchOutcome:
    """Kết quả phân tích batch để caller xử lý đúng từng loại lỗi."""
    OK = "ok"
    TRANSIENT_FAIL = "transient_fail"     # Rate limit / network → caller có thể retry
    STRUCTURAL_FAIL = "structural_fail"   # JSON malformed / contract vi phạm → đừng tăng retry, alert admin


def _classify_exception(exc: BaseException) -> str:
    """Nhận diện lỗi transient (đáng retry) vs structural (vô ích nếu retry)."""
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError, KeyError)):
        return _BatchOutcome.STRUCTURAL_FAIL
    if "rate" in msg or "429" in msg or "timeout" in msg or "connection" in msg or "network" in name:
        return _BatchOutcome.TRANSIENT_FAIL
    if "rate" in name or "timeout" in name or "apiconnection" in name:
        return _BatchOutcome.TRANSIENT_FAIL
    return _BatchOutcome.TRANSIENT_FAIL  # mặc định "đáng thử lại 1 lần" trừ khi rõ structural


def analyze_articles_batch(articles: List[Article], client: OpenAI) -> Tuple[str, List[Article]]:
    """
    Phân tích batch bằng 70B.

    Returns (outcome, missing_articles):
      - outcome  : OK | TRANSIENT_FAIL | STRUCTURAL_FAIL
      - missing  : danh sách bài LLM trả OK nhưng QUÊN không insight cho bài đó.
                   Bài missing đã được set processed=True + low_confidence=True bởi hàm này
                   để caller chỉ việc mark_processed mà KHÔNG tăng retry.
    """
    if not articles:
        return _BatchOutcome.OK, []

    batch_input = [
        {"id": a.id, "title": a.title, "summary": (a.summary or "")[:500]}
        for a in articles
    ]

    last_exc: Optional[BaseException] = None
    raw_content = ""
    raw_data: dict = {}

    if BACKUP_MODEL and BACKUP_MODEL != POWER_MODEL:
        # Có model dự phòng: primary fail (kể cả structural) → đổi model ngay, không backoff.
        attempt_models = [POWER_MODEL, BACKUP_MODEL]
    else:
        attempt_models = [POWER_MODEL] * (ANALYZE_TRANSIENT_RETRIES + 1)

    for attempt, model_name in enumerate(attempt_models):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_BATCH},
                    {"role": "user", "content": json.dumps(batch_input)},
                ],
                model=model_name,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content or "{}"
            raw_data = json.loads(raw_content)
            break
        except Exception as e:
            last_exc = e
            kind = _classify_exception(e)
            logger.warning(
                "Batch analyze attempt %d (model=%s) failed (%s): %s",
                attempt + 1, model_name, kind, e,
            )
            is_last = attempt == len(attempt_models) - 1
            next_model = None if is_last else attempt_models[attempt + 1]
            if kind == _BatchOutcome.STRUCTURAL_FAIL and next_model == model_name:
                # Structural error: retry cùng model vô ích trừ khi prompt thay đổi.
                return _BatchOutcome.STRUCTURAL_FAIL, []
            if is_last:
                if kind == _BatchOutcome.STRUCTURAL_FAIL:
                    return _BatchOutcome.STRUCTURAL_FAIL, []
                return _BatchOutcome.TRANSIENT_FAIL, []
            if next_model == model_name:
                time.sleep(ANALYZE_TRANSIENT_BACKOFF_S * (attempt + 1))
            continue

    results = raw_data.get("results", []) if isinstance(raw_data, dict) else []
    if not isinstance(results, list):
        logger.error("Batch response 'results' không phải list. raw=%s", raw_content[:300])
        return _BatchOutcome.STRUCTURAL_FAIL, []

    result_map: Dict[str, dict] = {}
    positional_results: List[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        positional_results.append(r)
        rid = r.get("id")
        if isinstance(rid, str) and rid:
            result_map[rid] = r

    rescue_count = 0
    missing: List[Article] = []

    for idx, article in enumerate(articles):
        res = result_map.get(article.id)
        if res is None and len(positional_results) == len(articles):
            res = positional_results[idx]
            logger.warning(
                "Batch: ID mismatch idx=%d (db=%s) → fallback positional. LLM id=%r",
                idx, article.id[:12], (res.get("id", "") if res else "")[:24],
            )

        if res is None:
            # Vector 3b: KHÔNG tăng retry, đánh dấu processed + low_confidence để
            # bài không kẹt vĩnh viễn trong queue. Caller sẽ mark_processed như bài
            # neutral bình thường và admin nhận được warning qua heartbeat.
            article.market_impact = MarketImpact.NEUTRAL
            article.sentiment = 0.0
            article.key_takeaway = "LLM did not return analysis (auto-closed)."
            article.narrative_tag = "Other"
            article.affected_tokens = []
            article.urgency = "context"
            article.low_confidence = True
            article.processed = True
            missing.append(article)
            continue

        try:
            article.sentiment = float(res.get("sentiment", 0.0))
        except (TypeError, ValueError):
            article.sentiment = 0.0
        article.market_impact = normalize_market_impact(res.get("market_impact", "neutral"))
        article.key_takeaway = str(res.get("key_takeaway", ""))[:300]
        article.narrative_tag = str(res.get("narrative_tag", "Other"))
        raw_tokens = res.get("affected_tokens", [])
        article.affected_tokens = [str(t) for t in raw_tokens[:3]] if isinstance(raw_tokens, list) else []
        article.urgency = str(res.get("urgency", "context"))

        if (
            article.market_impact == MarketImpact.NEUTRAL
            and article.sentiment is not None
            and abs(article.sentiment) >= SENTIMENT_RESCUE_THRESHOLD
        ):
            rescued = MarketImpact.BULLISH if article.sentiment > 0 else MarketImpact.BEARISH
            logger.info(
                "Sentiment rescue: id=%s sentiment=%+.2f -> %s (LLM said neutral)",
                article.id[:12], article.sentiment, rescued.value,
            )
            article.market_impact = rescued
            rescue_count += 1

        article.processed = True

    if missing:
        logger.warning(
            "Batch missing %d/%d articles. Marked processed+low_confidence to avoid retry-tax.",
            len(missing), len(articles),
        )
    if rescue_count:
        logger.info("Sentiment rescue cứu được %d/%d bài.", rescue_count, len(articles))

    return _BatchOutcome.OK, missing


def analyze_article(article: Article, client: OpenAI) -> bool:
    """Hỗ trợ luồng cũ bằng cách gọi batch size 1; trả True nếu OK."""
    outcome, _ = analyze_articles_batch([article], client)
    return outcome == _BatchOutcome.OK


# Public alias để caller import sạch hơn
BatchOutcome = _BatchOutcome
