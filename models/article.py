"""
models/article.py
=================
Data Contract trung tâm của CryptoSentinel (v2 — Python Pipeline).

Giải quyết 3 bài toán:
  1. Data Integrity    — Pydantic validate dữ liệu thô trước khi vào DB
  2. Deduplication     — ID = SHA-256(URL), PostgreSQL dùng ON CONFLICT làm cổng trùng
  3. Structured Insight — sentiment + MarketImpact Enum (không raw string)

Stack: Python 3.11+, pydantic >= 2.0
"""

import hashlib
import html
import re
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, computed_field, field_validator


# ===========================================================================
# Enums
# ===========================================================================

class MarketImpact(str, Enum):
    """
    Tác động của tin tức lên thị trường.

    QUAN TRỌNG: Đây là Enum, KHÔNG phải raw string.
    Lý do: LLM hay trả về "Bullish", "BULLISH", "bullish trend" — không nhất quán.
    Dùng Enum + normalize_market_impact() để đảm bảo filter trong notifier.py
    luôn hoạt động đúng.

    Notifier chỉ gửi Telegram với BULLISH và BEARISH.
    NEUTRAL bị lọc để giảm noise.
    """
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


_BULLISH_SYNONYMS = (
    "bullish", "positive", "pump", "rally", "upbeat",
    "favorable", "favourable", "uptrend", "up-trend", "up trend",
    "buy", "long", "moon", "green", "optimistic",
)
_BEARISH_SYNONYMS = (
    "bearish", "negative", "dump", "crash", "selloff", "sell-off",
    "unfavorable", "unfavourable", "downtrend", "down-trend", "down trend",
    "sell", "short", "red", "pessimistic",
)


def normalize_market_impact(raw: str) -> MarketImpact:
    """
    Chuyển đổi raw string từ LLM về MarketImpact Enum.

    Bug đã sửa (2026-05-07): llama-3.3-70b-versatile thường trả về
    "positive"/"negative" thay vì "bullish"/"bearish" mặc dù prompt
    yêu cầu rõ. Trước fix, mọi giá trị lạ đều rơi vào NEUTRAL → bot
    im lặng vĩnh viễn. Bảng từ điển bên dưới phủ các synonym phổ biến
    LLM hay nhả ra thay vì sửa cả prompt rồi cầu nguyện model nghe lời.

    Ví dụ:
        "Bullish"       → MarketImpact.BULLISH
        "positive"      → MarketImpact.BULLISH    # thường gặp với 70B
        "negative"      → MarketImpact.BEARISH
        "uptrend"       → MarketImpact.BULLISH
        "neutral"       → MarketImpact.NEUTRAL
        ""              → MarketImpact.NEUTRAL
    """
    cleaned = (raw or "").lower().strip()
    if not cleaned:
        return MarketImpact.NEUTRAL
    # Check bearish trước để "not bullish" không bị bullish-match (an toàn)
    if any(token in cleaned for token in _BEARISH_SYNONYMS):
        return MarketImpact.BEARISH
    if any(token in cleaned for token in _BULLISH_SYNONYMS):
        return MarketImpact.BULLISH
    return MarketImpact.NEUTRAL


# ===========================================================================
# Core Article Model
# ===========================================================================

class Article(BaseModel):
    """
    Đơn vị dữ liệu duy nhất trong pipeline CryptoSentinel.
    Mọi dữ liệu từ Scraper → PostgreSQL → LLM → Telegram đều là Article.

    Luồng điền dữ liệu:
        Scraper   → url, title, source, published_at, summary
        [auto]    → id (computed), scraped_at (default)
        LLM       → sentiment, market_impact, key_takeaway
        Storage   → processed (update sau khi LLM xong)
    """

    # --- Nhóm 1: Bắt buộc (Scraper phải cung cấp) ---
    url: HttpUrl = Field(
        description="URL gốc. Dùng để compute ID hash."
    )
    title: str = Field(
        min_length=5,
        max_length=500,
        description="Tiêu đề bài báo."
    )
    source: str = Field(
        description="Tên nguồn (ví dụ: 'The Block', 'CoinDesk')."
    )
    published_at: datetime = Field(
        description="Thời điểm đăng. Auto-force UTC nếu thiếu timezone."
    )

    # --- Nhóm 2: Optional — Scraper cung cấp nếu có ---
    summary: Optional[str] = Field(
        default=None,
        description="Mô tả từ RSS feed. Nhiều feed không có → để None, LLM dùng title."
    )

    # --- Nhóm 3: Optional — LLM điền sau ---
    sentiment: Optional[float] = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Sentiment score: -1.0 (rất tiêu cực) → +1.0 (rất tích cực)."
    )
    market_impact: Optional[MarketImpact] = Field(
        default=None,
        description="Tác động thị trường. PHẢI là Enum, không raw string. Dùng normalize_market_impact() khi set."
    )
    key_takeaway: Optional[str] = Field(
        default=None,
        max_length=300,
        description="1 câu tóm tắt, max 20 từ, phải có số liệu cụ thể. LLM viết theo The Block style."
    )

    # --- Nhóm 3b: Optional — LLM điền (signal quality fields) ---
    narrative_tag: Optional[str] = Field(
        default=None,
        description="Narrative tag: AI | RWA | DePIN | BTC_ETF | Regulation | Hack | Macro | Other",
    )
    affected_tokens: Optional[List[str]] = Field(
        default=None,
        description="Tối đa 3 token liên quan, format $SYMBOL. Ví dụ: ['$BTC', '$SOL']",
    )
    urgency: Optional[str] = Field(
        default=None,
        description="Mức khẩn cấp: breaking | important | context",
    )

    # --- Nhóm 4: Metadata hệ thống ---
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Thời điểm Scraper bắt được tin (auto)."
    )
    processed: bool = Field(
        default=False,
        description="LLM đã xử lý chưa. False → get_unprocessed() sẽ retry."
    )

    # ===========================================================================
    # Computed Fields
    # ===========================================================================

    @staticmethod
    def _sanitize_url(raw_url: str) -> str:
        """
        Chặt bỏ query params (utm_source, tz...) và trailing slash
        để cùng một bài báo luôn cho ra cùng một hash, bất kể tracking params.
        Ví dụ: theblock.co/post/123?utm_source=rss&tz=456 → theblock.co/post/123
        """
        parsed = urlparse(raw_url)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return clean.rstrip('/')

    @computed_field
    @property
    def id(self) -> str:
        """
        ID duy nhất = SHA-256(sanitized_url).
        URL được sanitize trước khi hash: chặt query params + trailing slash.
        """
        return hashlib.sha256(self._sanitize_url(str(self.url)).encode()).hexdigest()

    # ===========================================================================
    # Validators
    # ===========================================================================

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        """Loại bỏ ký tự thừa, normalize whitespace."""
        return " ".join(v.strip().split())

    @field_validator("published_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        """Đảm bảo luôn có timezone để so sánh thời gian nhất quán."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    # ===========================================================================
    # Business Logic
    # ===========================================================================

    @property
    def is_actionable(self) -> bool:
        """
        True nếu bài đáng gửi Telegram.
        Điều kiện: LLM đã xử lý VÀ market_impact là bullish hoặc bearish.
        Neutral bị loại để giảm noise — đây là feature, không phải bug.
        """
        if not self.processed:
            return False
        if self.market_impact is None:
            return False
        return self.market_impact != MarketImpact.NEUTRAL

    def format_telegram(self) -> str:
        """
        Format tin nhắn Telegram theo The Block style.
        Chỉ gọi khi is_actionable == True.
        """
        impact_emoji = "📈" if self.market_impact == MarketImpact.BULLISH else "📉"
        impact_label = self.market_impact.value.upper() if self.market_impact else "N/A"
        sentiment_str = f"{self.sentiment:+.2f}" if self.sentiment is not None else "N/A"

        lines = [
            f"{impact_emoji} {impact_label} | {self.source}",
            "",
            self.title,
            "",
            f"Sentiment: {sentiment_str}",
        ]
        if self.key_takeaway:
            lines.append(f"Key: \"{self.key_takeaway}\"")
        lines.extend(["", f"Source: {self.url}"])
        lines.append("")
        lines.append("⚠️ AI-generated insight. Verify data before trading.")

        return "\n".join(lines)

    def format_telegram_html(self) -> str:
        """
        Định dạng gửi Telegram với ``parse_mode: HTML``.
        Escape toàn bộ tiêu đề / takeaway / URL để không bị RSS phá markup (Markdown legacy dễ vỡ vì ``_``, ``*``).
        """
        impact_emoji = "📈" if self.market_impact == MarketImpact.BULLISH else "📉"
        label = html.escape(self.market_impact.value.upper() if self.market_impact else "N/A")
        source_esc = html.escape(self.source.strip())
        title_esc = html.escape(self.title)
        sentiment_str = (
            html.escape(f"{self.sentiment:+.2f}")
            if self.sentiment is not None
            else "N/A"
        )

        # Urgency prefix cho header
        urgency_prefix = {
            "breaking": "🔴 <b>BREAKING</b> | ",
            "important": "⚡ <b>IMPORTANT</b> | ",
        }.get(self.urgency or "context", "")

        lines = [
            f"{urgency_prefix}{impact_emoji} <b>{label}</b> | {source_esc}",
        ]

        # Narrative badge + affected tokens (dòng phụ ngay dưới header)
        meta_parts = []
        if self.narrative_tag and self.narrative_tag != "Other":
            meta_parts.append(f"🏷 <code>{html.escape(self.narrative_tag)}</code>")
        if self.affected_tokens:
            tokens_str = " ".join(f"<code>{html.escape(t)}</code>" for t in self.affected_tokens)
            meta_parts.append(f"🪙 {tokens_str}")
        if meta_parts:
            lines.append("  ".join(meta_parts))

        lines.extend(["", title_esc, "", f"Sentiment: {sentiment_str}"])

        if self.key_takeaway:
            kt = html.escape(self.key_takeaway)
            lines.append(f'Key: <i>"{kt}"</i>')

        href = html.escape(str(self.url))
        lines.extend(["", f'<a href="{href}">Source link</a>', ""])
        lines.append("⚠️ AI-generated insight. Verify data before trading.")
        return "\n".join(lines)


# ===========================================================================
# Smoke Test — chạy: python models/article.py
# ===========================================================================

if __name__ == "__main__":
    from datetime import timedelta
    from pydantic import ValidationError

    print("=" * 60)
    print("TEST 1: Bài hợp lệ + normalize market_impact")
    print("=" * 60)

    article = Article(
        url="https://www.theblock.co/post/123/eth-wallet-sanctioned",
        title="U.S. Treasury Sanctions ETH Wallet Linked to Sinaloa Cartel",
        source="The Block",
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
        summary="OFAC added wallet 0x3a...f2 to SDN list. $12.4M USDT...",
        sentiment=-0.8,
        market_impact=normalize_market_impact("Bearish move by regulators"),
        key_takeaway="OFAC sanctions DeFi mixer wallet with $12.4M in illicit flows",
        processed=True,
    )

    print(f"ID      : {article.id[:20]}...")
    print(f"Impact  : {article.market_impact}")
    print(f"Actionable: {article.is_actionable}")
    print()
    print("--- Telegram Format ---")
    print(article.format_telegram())

    print()
    print("=" * 60)
    print("TEST 2: normalize_market_impact với các giá trị LLM hay trả về")
    print("=" * 60)

    test_cases = [
        # Canonical
        "Bullish", "BULLISH", "bullish trend",
        "Bearish", "BEARISH", "bearish pressure",
        "neutral", "NEUTRAL", "",
        # Synonym phổ biến từ LLM (bug 2026-05-07)
        "positive", "Positive", "negative", "Negative",
        "uptrend", "downtrend", "pump", "dump", "rally", "crash",
        "buy", "sell", "long", "short",
        # Edge cases
        "unknown", "N/A", "mixed",
    ]
    for raw in test_cases:
        result = normalize_market_impact(raw)
        print(f"  {raw!r:25} → {result.value}")

    print()
    print("=" * 60)
    print("TEST 3: Data Integrity — thiếu title → ValidationError")
    print("=" * 60)

    try:
        bad = Article(
            url="https://www.theblock.co/post/999",
            title="ab",  # Quá ngắn, min_length=5
            source="Unknown",
            published_at=datetime.now(timezone.utc),
        )
    except ValidationError as e:
        print(f"✅ Pydantic chặn đúng: {e.errors()[0]['msg']}")

    print()
    print("✅ Tất cả tests passed.")
