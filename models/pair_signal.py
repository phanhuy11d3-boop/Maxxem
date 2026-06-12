"""
models/pair_signal.py
================
Data contract trung tâm của CryptoSentinel (v3 — DEX-only).

PairSignal = MỘT biến động giá của MỘT pair, đo trực tiếp từ DEXScreener API.
Không có sentiment. Không có bullish/bearish. Không có LLM.
Hướng đi của giá là dữ kiện số (change_pct dương/âm), không phải nhãn suy đoán.

Luồng điền dữ liệu:
    Scanner  → toàn bộ field số liệu từ API response
    [auto]   → id (sha256 dedup_key), observed_at
    Storage  → outbox state (tg_status...) nằm ở DB, không nằm trong model
"""

import hashlib
import html
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

HORIZONS = ("m5", "h1", "h6", "h24")
HORIZON_LABEL = {"m5": "5m", "h1": "1h", "h6": "6h", "h24": "24h"}

# Ngưỡng phân loại độ nóng — m5 pump/dump mạnh là tin khẩn với trader
HOT_M5_ABS_PCT = 8.0
HOT_ANY_ABS_PCT = 15.0

# Swap link theo chain (pattern buy-bot thị trường: alert nào cũng có nút mua ngay).
# Chỉ map chain đã kiểm chứng URL; chain lạ → bỏ link Swap, không đoán.
_SWAP_URL_BY_CHAIN = {
    "solana": "https://jup.ag/swap/SOL-{address}",
    "ethereum": "https://app.uniswap.org/swap?outputCurrency={address}&chain=mainnet",
}

# Thanh độ lớn kiểu Whale Alert: emoji lặp theo biên độ move
_MAGNITUDE_TIERS = (5.0, 10.0, 20.0, 50.0)  # ≥ tier nào thì thêm 1 emoji

# Thanh áp lực mua 🟢🔴 chỉ hiện khi đủ mẫu — vài txn lẻ thì tỷ lệ vô nghĩa
_PRESSURE_MIN_TXNS = 10
_PRESSURE_SLOTS = 8


def magnitude_emojis(change_pct: float) -> str:
    """🚀 (pump) / 🩸 (dump) lặp 1-5 lần theo |%| — cảm nhận độ lớn trước khi đọc số."""
    icon = "🚀" if change_pct > 0 else "🩸"
    count = 1 + sum(1 for tier in _MAGNITUDE_TIERS if abs(change_pct) >= tier)
    return icon * count


def pressure_bar(buys: int, sells: int) -> Optional[str]:
    """Thanh 🟢🔴 8 ô theo tỷ lệ buy/sell, kèm % và số thô. None nếu thiếu mẫu."""
    total = buys + sells
    if total < _PRESSURE_MIN_TXNS:
        return None
    ratio = buys / total
    green = round(ratio * _PRESSURE_SLOTS)
    # Có cả mua lẫn bán thì bar không được phép trông tuyệt đối
    green = max(1, min(_PRESSURE_SLOTS - 1, green)) if 0 < buys and 0 < sells else green
    return f"{'🟢' * green}{'🔴' * (_PRESSURE_SLOTS - green)} {ratio:.0%} buys ({buys:,}/{sells:,})"


def fmt_usd_compact(value: float) -> str:
    """$1.2B / $850.0K / $2.34 — kiểu hiển thị DEXScreener."""
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.2f}"


def fmt_price(value: float) -> str:
    """Giá token: nhiều thập phân hơn khi giá nhỏ (meme coin)."""
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 1:
        return f"${value:,.2f}"
    if value >= 0.01:
        return f"${value:.4f}"
    return f"${value:.8f}"


def fmt_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


class PairSignal(BaseModel):
    """Một alert biến động giá pair — đơn vị dữ liệu duy nhất của pipeline."""

    # --- Định danh pair (bắt buộc, từ API) ---
    chain_id: str = Field(description="Chain trên DEXScreener, vd 'solana', 'ethereum'.")
    dex_id: str = Field(default="", description="DEX, vd 'raydium', 'uniswap'.")
    pair_address: str = Field(description="Địa chỉ pair — định danh tuyệt đối, không nhầm token.")
    base_symbol: str = Field(description="Symbol token base, vd 'WIF'.")
    quote_symbol: str = Field(description="Symbol token quote, vd 'SOL'.")
    base_address: Optional[str] = Field(
        default=None,
        description="Địa chỉ contract/mint của token base — dùng dựng link Swap.",
    )
    url: str = Field(description="Link chart DEXScreener.")

    # --- Biến động kích hoạt alert ---
    horizon: str = Field(description="Khung thời gian kích hoạt: m5|h1|h6|h24.")
    change_pct: float = Field(description="% thay đổi giá ở khung kích hoạt. Dấu = hướng đi.")

    # --- Số liệu bằng chứng (tất cả từ API, không suy đoán) ---
    price_usd: float = Field(ge=0)
    volume_usd: float = Field(ge=0, description="Volume USD ở khung kích hoạt.")
    liquidity_usd: float = Field(ge=0)
    buys: int = Field(ge=0, description="Số lệnh mua ở khung kích hoạt.")
    sells: int = Field(ge=0, description="Số lệnh bán ở khung kích hoạt.")
    changes: Dict[str, float] = Field(
        default_factory=dict,
        description="% thay đổi mọi khung {m5,h1,h6,h24} — dòng context đa khung.",
    )
    fdv: Optional[float] = Field(default=None, ge=0)
    market_cap: Optional[float] = Field(default=None, ge=0)

    # --- Metadata ---
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Thời điểm scanner đo được số liệu (UTC).",
    )
    dedup_key: str = Field(
        description="dex:{chain}:{pair}:{horizon}:{direction}:{bucket} — chống spam theo cooldown.",
    )
    low_liquidity: bool = Field(
        default=False,
        description="True nếu thanh khoản dưới ngưỡng tin cậy — gắn cảnh báo DYOR.",
    )

    @field_validator("horizon")
    @classmethod
    def horizon_known(cls, v: str) -> str:
        if v not in HORIZONS:
            raise ValueError(f"horizon phải thuộc {HORIZONS}")
        return v

    @field_validator("observed_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @computed_field
    @property
    def id(self) -> str:
        return hashlib.sha256(self.dedup_key.encode()).hexdigest()

    @property
    def pair_label(self) -> str:
        return f"{self.base_symbol.upper()}/{self.quote_symbol.upper()}"

    @property
    def direction(self) -> str:
        """'UP' | 'DOWN' — dữ kiện số, không phải nhận định thị trường."""
        return "UP" if self.change_pct > 0 else "DOWN"

    @property
    def is_hot(self) -> bool:
        """Move đủ mạnh để đẩy thêm kênh premium (m5 ≥8% hoặc bất kỳ khung ≥15%)."""
        a = abs(self.change_pct)
        return (self.horizon == "m5" and a >= HOT_M5_ABS_PCT) or a >= HOT_ANY_ABS_PCT

    @property
    def swap_url(self) -> Optional[str]:
        """Link mua/bán nhanh theo chain. None nếu chain chưa map hoặc thiếu address."""
        template = _SWAP_URL_BY_CHAIN.get(self.chain_id.lower())
        if not template or not self.base_address:
            return None
        return template.format(address=self.base_address)

    # ------------------------------------------------------------------
    # Telegram render — layout bảng giá kiểu DEXScreener
    # ------------------------------------------------------------------

    def format_telegram_html(self) -> str:
        """
        Format copy theo các kênh price-alert hút user nhất thị trường
        (Whale Alert, buy-bot Maestro-style, Drops Bot, kênh trending DEX):

            🚀🚀🚀 $WIF +12.4% · 1h ⚡
            🟢🟢🟢🟢🟢🔴🔴🔴 67% buys (221/109)

            💰 $2.345 — WIF/SOL · Raydium · Solana
            ⏳ 5m +1.1% | 1h +12.4% | 6h +8.0% | 24h +15.3%
            📊 Vol $850.0K · 💧 Liq $2.4M · 🧢 MC $2.2B

            📈 Chart | 🔁 Swap
            #WIF #Solana ⏱ 23:04 ICT

        5 pattern thị trường: emoji lặp theo độ lớn (Whale Alert), cashtag
        tap-được, thanh áp lực mua 🟢🔴, hàng link hành động Chart|Swap,
        hashtag lọc coin. Mọi con số vẫn 100% từ API — không opinion.
        """
        cashtag = html.escape(f"${self.base_symbol.upper().lstrip('$')}")
        h_label = HORIZON_LABEL[self.horizon]
        hot = " ⚡" if self.is_hot else ""
        dex = html.escape(self.dex_id.capitalize()) if self.dex_id else ""
        chain_name = html.escape(self.chain_id.capitalize())
        venue = f"{dex} · {chain_name}" if dex else chain_name

        lines = [
            f"{magnitude_emojis(self.change_pct)} <b>{cashtag} {fmt_pct(self.change_pct)}</b> · {h_label}{hot}",
        ]
        bar = pressure_bar(self.buys, self.sells)
        if bar:
            lines.append(bar)

        lines.extend([
            "",
            f"💰 {fmt_price(self.price_usd)} — {html.escape(self.pair_label)} · {venue}",
        ])

        if self.changes:
            multi = " | ".join(
                f"{HORIZON_LABEL[h]} {fmt_pct(self.changes[h])}"
                for h in HORIZONS if h in self.changes
            )
            if multi:
                lines.append(f"⏳ {multi}")

        stats = (
            f"📊 Vol {fmt_usd_compact(self.volume_usd)} · "
            f"💧 Liq {fmt_usd_compact(self.liquidity_usd)}"
        )
        if self.market_cap:
            stats += f" · 🧢 MC {fmt_usd_compact(self.market_cap)}"
        lines.append(stats)
        if not bar and (self.buys or self.sells):
            lines.append(f"🟢 {self.buys:,} buys · 🔴 {self.sells:,} sells")
        if self.low_liquidity:
            lines.append("⚠️ Low liquidity — DYOR")

        chart_href = html.escape(self.url)
        actions = f'<a href="{chart_href}">📈 Chart</a>'
        if self.swap_url:
            actions += f' | <a href="{html.escape(self.swap_url)}">🔁 Swap</a>'
        obs_ict = self.observed_at.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M")
        tags = f"#{self.base_symbol.upper().lstrip('$')} #{self.chain_id.capitalize()}"
        lines.extend(["", actions, f"{html.escape(tags)} ⏱ {obs_ict} ICT"])
        return "\n".join(lines)


# ===========================================================================
# Smoke test — chạy: py -3 models/pair_signal.py
# ===========================================================================

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sig = PairSignal(
        chain_id="solana",
        dex_id="raydium",
        pair_address="EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
        base_symbol="WIF",
        quote_symbol="SOL",
        base_address="EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        url="https://dexscreener.com/solana/EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
        horizon="h1",
        change_pct=12.4,
        price_usd=2.345,
        volume_usd=850_000,
        liquidity_usd=2_400_000,
        buys=221,
        sells=109,
        changes={"m5": 1.1, "h1": 12.4, "h6": 8.0, "h24": 15.3},
        market_cap=2_200_000_000,
        dedup_key="dex:solana:EP2ib:h1:UP:202606121000",
    )
    print(f"id        : {sig.id[:16]}…")
    print(f"direction : {sig.direction} | hot={sig.is_hot}")
    print()
    print(sig.format_telegram_html())
