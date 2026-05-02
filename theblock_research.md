# CryptoSentinel — Phong Cách The Block (Reference Only)

> **Mục đích của file này:** Tài liệu tham khảo để LLM (Groq) viết đúng phong cách.
> File này được `processors/insight_extractor.py` đọc khi xây dựng System Prompt.

---

## Nguyên tắc Nội dung The Block (áp dụng vào key_takeaway)

### 1. Headline — "Subject + Action + Data"

| ❌ Không viết | ✅ Viết đúng |
|---|---|
| "Bitcoin pumps hard!!!" | "Bitcoin rises to $70K as spot ETF inflows hit $500M daily" |
| "BREAKING: Huge whale move!" | "500M USDT transferred from Binance amid leverage unwind" |
| "This altcoin is the next 100x" | "Arbitrum TVL grows 15% in Q3 as DeFi shifts to L2" |

**Quy tắc cho `key_takeaway`:**
- 1 câu duy nhất, tối đa 20 từ
- Có số liệu cụ thể (%, $, số lượng)
- Giải thích "tại sao" ngay trong câu
- Không dùng: "revolutionary", "game-changer", "groundbreaking", "huge", "massive", "moon"

---

### 2. Sentiment Score Calibration

Đây là ngưỡng tham chiếu để LLM gán điểm nhất quán:

| Loại tin | Sentiment range | Ví dụ |
|---|---|---|
| SEC approve ETF | +0.7 → +1.0 | Regulatory green light |
| Protocol upgrade thành công | +0.3 → +0.6 | Technical progress |
| Tin trung lập / routine | -0.2 → +0.2 | Volume report, partnership minor |
| Hack/exploit | -0.5 → -0.8 | Protocol bị tấn công |
| Ban/sanctions/major fine | -0.7 → -1.0 | Regulatory crackdown |

---

### 3. Market Impact Decision Tree

```
Tin tức → LLM đánh giá:
  ├── Tăng demand hoặc giảm supply → "bullish"
  ├── Giảm demand hoặc tăng supply/risk → "bearish"
  └── Không ảnh hưởng rõ ràng → "neutral"
```

**Lưu ý:** Notifier chỉ gửi Telegram với "bullish" và "bearish".
"neutral" bị lọc để giảm noise. Đây là **tính năng, không phải lỗi**.

---

### 4. Nguồn RSS được cấu hình trong `config/sources.yaml`

| Source | Feed URL | Category mặc định |
|---|---|---|
| The Block | `https://www.theblock.co/rss.xml` | ECOSYSTEM |
| CoinDesk | `https://www.coindesk.com/arc/outboundfeeds/rss/` | MACRO |
| CoinTelegraph | `https://cointelegraph.com/rss` | EXCHANGES |

---

## Trạng thái dự án (theo kiến trúc v2)

| Phase | Module | Trạng thái |
|---|---|---|
| Phase 1 | `models/article.py` | ✅ Đã có — cần cập nhật |
| Phase 2 | `storage/sqlite.py` | ⬜ Chưa làm |
| Phase 3 | `scrapers/generic_rss.py` | ⬜ Chưa làm |
| Phase 4 | `processors/insight_extractor.py` | ⬜ Chưa làm |
| Phase 5 | `utils/notifier.py` | ⬜ Chưa làm |
| Phase 6 | `main.py` + `.github/workflows/scraper.yml` | ⬜ Chưa làm |
