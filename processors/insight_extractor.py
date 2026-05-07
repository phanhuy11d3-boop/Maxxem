"""
processors/insight_extractor.py
===============================
Mô-đun tương tác với Groq API.
Tối ưu hóa Token FinOps: Tiered LLM (8B -> 70B) & Batch Processing.
"""

import os
import json
import time
import logging
from typing import Optional, Dict, Any, List

from groq import Groq
from models.article import Article, MarketImpact, normalize_market_impact

logger = logging.getLogger(__name__)

# --- CONFIG ---
FAST_MODEL = "llama-3.1-8b-instant"
POWER_MODEL = "llama-3.3-70b-versatile"

# Rescue threshold: nếu LLM trả market_impact="neutral" nhưng |sentiment| đủ mạnh,
# suy ngược ra direction. Tránh trường hợp model nhả "neutral" + sentiment=0.7 vô lý.
SENTIMENT_RESCUE_THRESHOLD = 0.4

# --- PROMPTS (Optimized for tokens) ---
TRIAGE_PROMPT = """Act as a crypto news filter. 
Decide if each news title is 'high_impact' (market moving, hacks, major funding, regulatory) or 'low_impact' (routine, fluff, PR).
Return JSON: {"results": [true, false, ...]} matching the input order."""

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

def get_groq_client() -> Optional[Groq]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("Chưa cấu hình GROQ_API_KEY.")
        return None
    return Groq(api_key=api_key)

def triage_articles(articles: List[Article], client: Groq) -> List[bool]:
    """Tier 1: Dùng model 8B siêu rẻ để lọc tin rác theo Batch."""
    if not articles: return []
    
    titles = [a.title for a in articles]
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": TRIAGE_PROMPT},
                {"role": "user", "content": json.dumps(titles)}
            ],
            model=FAST_MODEL,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("results", [True] * len(articles))
    except Exception as e:
        logger.error(f"Triage error: {e}")
        return [True] * len(articles) # Fallback: cho qua hết nếu lỗi

def analyze_articles_batch(articles: List[Article], client: Groq) -> bool:
    """Tier 2: Dùng model 70B xử lý Batch các tin quan trọng đã qua lọc."""
    if not articles: return True
    
    # Chuẩn bị dữ liệu batch để gửi (giảm overhead token)
    batch_input = [
        {"id": a.id, "title": a.title, "summary": (a.summary or "")[:500]}
        for a in articles
    ]
    
    try:
        # FinOps: Delay để tránh rate limit nếu cần, nhưng batch giúp giảm số lần gọi
        time.sleep(1)
        
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_BATCH},
                {"role": "user", "content": json.dumps(batch_input)}
            ],
            model=POWER_MODEL,
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        raw_content = response.choices[0].message.content
        raw_data = json.loads(raw_content)
        results = raw_data.get("results", [])

        # Map kết quả lại vào object Article. Khớp theo id chuẩn; fallback theo
        # vị trí (positional) nếu LLM bóp méo id — tránh queue stuck retry vĩnh viễn.
        result_map = {res["id"]: res for res in results if isinstance(res, dict) and "id" in res}
        positional_results = [r for r in results if isinstance(r, dict)]

        rescue_count = 0
        missing_count = 0
        for idx, article in enumerate(articles):
            res = result_map.get(article.id)
            if res is None and idx < len(positional_results):
                # Position-based fallback chỉ dùng khi LLM trả đúng số lượng
                if len(positional_results) == len(articles):
                    res = positional_results[idx]
                    logger.warning(
                        "ID mismatch cho article idx=%s (%s...), fallback positional. LLM id='%s'",
                        idx, article.id[:12], res.get("id", "")[:24],
                    )

            if res is None:
                missing_count += 1
                logger.warning(
                    "Batch response missing ID cho article id=%s title=%r",
                    article.id[:12], (article.title or "")[:80],
                )
                continue

            article.sentiment = float(res.get("sentiment", 0.0))
            article.market_impact = normalize_market_impact(res.get("market_impact", "neutral"))
            article.key_takeaway = str(res.get("key_takeaway", ""))[:300]
            article.narrative_tag = str(res.get("narrative_tag", "Other"))
            raw_tokens = res.get("affected_tokens", [])
            article.affected_tokens = [str(t) for t in raw_tokens[:3]] if isinstance(raw_tokens, list) else []
            article.urgency = str(res.get("urgency", "context"))

            # Sentiment rescue: |sentiment| đủ mạnh nhưng impact bị NEUTRAL → suy ngược.
            # Lý do tồn tại: prompt cấm "positive/negative" nhưng llama-3.3 vẫn nhả ra
            # và normalize_market_impact đã xử lý. Đây là vành đai phòng thủ thứ hai cho
            # case LLM trả "mixed"/"uncertain" + sentiment đậm.
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

        if missing_count:
            logger.warning(
                "Batch missing %s/%s articles. Raw response head: %s",
                missing_count, len(articles), raw_content[:400],
            )
        if rescue_count:
            logger.info("Sentiment rescue cứu được %s/%s bài.", rescue_count, len(articles))

        return True
    except Exception as e:
        logger.error(f"Batch analysis error: {e}")
        return False

# Legacy support: keep original function but make it a wrapper or just leave it for small calls
def analyze_article(article: Article, client: Groq) -> bool:
    """Hỗ trợ luồng cũ bằng cách gọi batch size 1."""
    return analyze_articles_batch([article], client)
