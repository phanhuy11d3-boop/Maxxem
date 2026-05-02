"""
processors/insight_extractor.py
===============================
Mô-đun tương tác với Groq API (Llama 3) để phân tích bài báo.
Biến text thô thành tín hiệu có cấu trúc (sentiment, impact, takeaway).
"""

import os
import json
import time
import logging
import re
from typing import Optional, Dict, Any

from groq import Groq

from models.article import Article, normalize_market_impact

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are CryptoSentinel, a hyper-specialized autonomous crypto analyst.
Your persona:
- Skeptical, data-driven, and technical.
- Ignore social media noise and marketing hype.
- Do not recognize 'revolutionary' or 'game-changing' as valid descriptors.
- Focus on liquidity flows and verifiable unit economics.
- Tone: Cold, precise, and concise. Never friendly or polite.

Analyze the following news title and summary. Return ONLY a valid JSON object with exactly these fields:
{
  "sentiment": <float from -1.0 to 1.0>,
  "market_impact": <"bullish" | "bearish" | "neutral">,
  "key_takeaway": <max 20 words, must be a skeptical, evidence-based insight, no hype words>
}
Do not include any explanation, markdown, or text outside the JSON object."""

def get_groq_client() -> Optional[Groq]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("Chưa cấu hình GROQ_API_KEY trong environment variables.")
        return None
    return Groq(api_key=api_key)

def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Cố gắng bóc tách JSON object từ text trả về của LLM."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
        
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
            
    return None

def analyze_article(article: Article, client: Groq, model: str = "llama-3.3-70b-versatile") -> bool:
    """
    Gọi Groq API để phân tích Article. 
    Nếu thành công, update trực tiếp vào object Article.
    Trả về True nếu thành công, False nếu thất bại.
    """
    user_content = f"Title: {article.title}\nSummary: {article.summary or 'No summary'}"
    
    try:
        # Rate limit: Chặn spam API, giới hạn 2 giây / call theo FinOps plan
        time.sleep(2)
        
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            model=model,
            temperature=0.0, # Giảm độ "ngáo/sáng tạo", bắt buộc phải phân tích chính xác, khô khan
            response_format={"type": "json_object"}
        )
        
        raw_output = response.choices[0].message.content
        if not raw_output:
            logger.warning(f"Groq API trả về rỗng cho ID {article.id}")
            return False
            
        data = extract_json_from_text(raw_output)
        if not data:
            logger.warning(f"Không thể parse JSON từ Groq cho ID {article.id}. Raw: {raw_output}")
            return False
            
        # Update AI insights thẳng vào object Article
        # Tự động catch lỗi nếu LLM văng ra format rác (vd: "bearish trend") nhờ hàm normalize_market_impact
        article.sentiment = float(data.get("sentiment", 0.0))
        article.market_impact = normalize_market_impact(data.get("market_impact", "neutral"))
        article.key_takeaway = str(data.get("key_takeaway", ""))[:300]
        
        return True
        
    except Exception as e:
        logger.error(f"Lỗi khi gọi Groq API cho ID {article.id}: {e}")
        return False

# ===========================================================================
# Smoke Test — chạy: python processors/insight_extractor.py
# ===========================================================================
if __name__ == "__main__":
    from datetime import datetime, timezone
    import sys
    
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    print("=" * 60)
    print("TEST: Chạy Insight Extractor (Yêu cầu có GROQ_API_KEY)")
    
    client = get_groq_client()
    if client:
        test_article = Article(
            url="https://test.com",
            title="Bitcoin ETFs See Record $1 Billion Inflow in Single Day",
            source="Test",
            published_at=datetime.now(timezone.utc),
            summary="Institutional adoption accelerates as spot Bitcoin ETFs log their highest single-day inflows since launch, pushing BTC past $70k."
        )
        
        print(f"Đang phân tích: {test_article.title}")
        success = analyze_article(test_article, client)
        
        if success:
            print("\nKết quả AI Insights:")
            print(f"  Sentiment    : {test_article.sentiment}")
            print(f"  Market Impact: {test_article.market_impact.value.upper()}")
            print(f"  Key Takeaway : {test_article.key_takeaway}")
        else:
            print("Phân tích thất bại.")
    else:
        print("Bỏ qua test vì chưa có biến môi trường GROQ_API_KEY.")
