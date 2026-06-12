"""
models/signal.py
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

    # ------------------------------------------------------------------
    # Telegram render — layout bảng giá kiểu DEXScreener
    # ------------------------------------------------------------------

    def format_telegram_html(self) -> str:
        """
        Bảng giá đọc 2 giây là hiểu — hook nằm ở ký tự đầu tiên:

            🚀 WIF/SOL +12.4% · 1h
            💰 $2.345 · Raydium · Solana
            ⏳ 5m +1.1% | 1h +12.4% | 6h +8.0% | 24h +15.3%
            📊 Vol 1h $850.0K · 💧 Liq $2.4M
            🟢 221 buys · 🔴 109 sells
            🧢 MC $2.2B

            📈 Chart — DEXScreener
            ⏱ 23:04 ICT

        Mọi con số đều từ API. Không nhãn bullish/bearish, không lời bình AI.
        """
        arrow = "🚀" if self.change_pct > 0 else "🩸"
        pair = html.escape(self.pair_label)
        h_label = HORIZON_LABEL[self.horizon]
        dex = html.escape(self.dex_id.capitalize()) if self.dex_id else ""
        chain = html.escape(self.chain_id.capitalize())
        venue = f"{dex} · {chain}" if dex else chain

        lines = [
            f"{arrow} <b>{pair} {fmt_pct(self.change_pct)}</b> · {h_label}",
            f"💰 {fmt_price(self.price_usd)} · {venue}",
        ]

        if self.changes:
            multi = " | ".join(
                f"{HORIZON_LABEL[h]} {fmt_pct(self.changes[h])}"
                for h in HORIZONS if h in self.changes
            )
            if multi:
                lines.append(f"⏳ {multi}")

        lines.append(
            f"📊 Vol {h_label} {fmt_usd_compact(self.volume_usd)} · "
            f"💧 Liq {fmt_usd_compact(self.liquidity_usd)}"
        )
        lines.append(f"🟢 {self.buys:,} buys · 🔴 {self.sells:,} sells")
        if self.market_cap:
            lines.append(f"🧢 MC {fmt_usd_compact(self.market_cap)}")
        if self.low_liquidity:
            lines.append("⚠️ Low liquidity — DYOR")

        obs_ict = self.observed_at.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M")
        href = html.escape(self.url)
        lines.extend(["", f'<a href="{href}">📈 Chart — DEXScreener</a>', f"⏱ {obs_ict} ICT"])
        return "\n".join(lines)


# ===========================================================================
# Smoke test — chạy: py -3 models/signal.py
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
