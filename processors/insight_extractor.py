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
from models.article import Article, normalize_market_impact

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIG ---
FAST_MODEL = "llama-3.1-8b-instant"
POWER_MODEL = "llama-3.3-70b-versatile"

# --- PROMPTS (Optimized for tokens) ---
TRIAGE_PROMPT = """Act as a crypto news filter. 
Decide if each news title is 'high_impact' (market moving, hacks, major funding, regulatory) or 'low_impact' (routine, fluff, PR).
Return JSON: {"results": [true, false, ...]} matching the input order."""

SYSTEM_PROMPT_BATCH = """You are CryptoSentinel: skeptical, data-driven. Use ONLY title/summary provided.
Rules:
- Do not infer numbers or facts absent from input. If insufficient → sentiment near 0, market_impact "neutral".
- key_takeaway: max 20 words, dry tone; include at least one concrete number (%, $, count) copied from input when possible.
  If input has none, state uncertainty without hype.
- Forbidden in key_takeaway: revolutionary, game-changer, groundbreaking, massive, huge, moon, explode, skyrocket.
For each article return id, sentiment (-1..1), market_impact (bullish|bearish|neutral), key_takeaway.
JSON only: {"results": [{"id": "...", "sentiment": 0.0, "market_impact": "neutral", "key_takeaway": "..."}]}"""

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
        
        raw_data = json.loads(response.choices[0].message.content)
        results = raw_data.get("results", [])
        
        # Map kết quả lại vào object Article
        result_map = {res["id"]: res for res in results if "id" in res}
        
        for article in articles:
            if article.id in result_map:
                res = result_map[article.id]
                article.sentiment = float(res.get("sentiment", 0.0))
                article.market_impact = normalize_market_impact(res.get("market_impact", "neutral"))
                article.key_takeaway = str(res.get("key_takeaway", ""))[:300]
                article.processed = True
            else:
                logger.warning(f"Batch response missing ID: {article.id}")
                
        return True
    except Exception as e:
        logger.error(f"Batch analysis error: {e}")
        return False

# Legacy support: keep original function but make it a wrapper or just leave it for small calls
def analyze_article(article: Article, client: Groq) -> bool:
    """Hỗ trợ luồng cũ bằng cách gọi batch size 1."""
    return analyze_articles_batch([article], client)
