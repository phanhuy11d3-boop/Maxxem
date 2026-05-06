# Skill: CryptoSentinel AIOS Structural Audit (Orchestrator)

> **Mục tiêu:** Đánh giá định kỳ xem CryptoSentinel AIOS có được xây đúng như một hệ điều hành agentic hay chưa: đủ Context, Connections, Capabilities và Cadence.

## 1. Khi nào dùng skill này
- Khi người dùng yêu cầu "audit AIOS", "kiểm tra hệ thống", "đánh giá Four Cs", "AIOS có hoạt động đúng không", hoặc muốn tìm lỗ hổng cấu trúc của CryptoSentinel.
- Đây là audit cấu trúc, không phải audit chất lượng tin tức. Nếu cần kiểm chứng hallucination/FUD, dùng `audit-security-skill.md`.
- Mặc định chỉ đọc. Chỉ tạo report trong `audits/` nếu người dùng xác nhận muốn lưu.

## 2. Phạm vi kiểm tra

Đánh giá theo 4 trụ cột, tổng 100 điểm:

| Layer | Câu hỏi kiểm định |
|---|---|
| **Context** | Agents, rules, manual và memory có đủ để AI hiểu vai trò CryptoSentinel không? |
| **Connections** | Python tools có chạm được nguồn tin, database, LLM và Telegram không? |
| **Capabilities** | Skills, agents và executable checks có đủ để vận hành pipeline không? |
| **Cadence** | GitHub Actions, state và lệnh vận hành có tạo vòng lặp tự động không? |

## 3. Checklist khám phá nhanh

Kiểm tra các nhóm file sau, linh hoạt với tên tương đương:

- **Manual & rules:** `CLAUDE.md`, `AGENTS.md`, `.claude/rules/`.
- **Agents:** `.claude/agents/*.md`, `.codex/agents/*.toml`, `.agents/`.
- **Skills:** `.claude/skills/*.md`, `.claude/skills/*/SKILL.md`, `.agents/skills/`.
- **Connections:** `scrapers/`, `storage/`, `utils/`, `processors/`, `config/sources.yaml`, `.env.example`.
- **Runtime cadence:** `.github/workflows/`, `storage/state.json`, `main.py`, `scripts/audit_agent.py`.
- **Contracts & tests:** `models/article.py`, `tests/`, `tests/data/golden_dataset.json`.

Không phạt nếu tên thư mục không canonical nhưng ý định và chức năng tương đương đã tồn tại.

## 4. Scoring

### Context (25 pts)
| Tiêu chí | Điểm |
|---|---:|
| Operating manual tồn tại và mô tả AIOS rõ ràng (`CLAUDE.md` hoặc `AGENTS.md`) | 5 |
| Role/mission của CryptoSentinel và agent boundaries được ghi nhận | 5 |
| Agent definitions đủ 5 vai trò: Scout, Analyst, Auditor, Broadcaster, Orchestrator | 5 |
| Rules/SOP/reference docs tồn tại để giữ hành vi nhất quán | 5 |
| State hoặc memory artifact tồn tại để lưu vòng lặp ngắn hạn | 5 |

### Connections (25 pts)
| Tiêu chí | Điểm |
|---|---:|
| RSS/news ingestion có nguồn cấu hình trong `config/sources.yaml` và scraper tương ứng | 5 |
| Database persistence có Postgres/Supabase path và schema contract rõ | 5 |
| LLM analysis connection có env contract và processor tương ứng | 5 |
| Telegram/broadcast connection có notifier và env contract | 5 |
| Connection freshness: source config, env example và runtime path không mâu thuẫn | 5 |

### Capabilities (25 pts)
| Tiêu chí | Điểm |
|---|---:|
| Có ít nhất 4 skill vận hành cho ingestion, insight, audit, broadcast hoặc orchestration | 8 |
| Có đủ agent brains cho pipeline end-to-end | 6 |
| Có executable audit/guard (`scripts/audit_agent.py` hoặc tương đương) | 5 |
| Data contract trung tâm tồn tại (`models/article.py`) | 3 |
| Có golden dataset hoặc test artifact để kiểm hồi quy | 3 |

### Cadence (25 pts)
| Tiêu chí | Điểm |
|---|---:|
| Có recurring workflow trong `.github/workflows/` cho scraper/pipeline | 8 |
| Có CI/guard workflow hoặc audit command tự động | 6 |
| `storage/state.json` hoặc state store được dùng để tránh chạy mù | 5 |
| `main.py` hỗ trợ chế độ vận hành rõ (`--legacy`, `--agentic` hoặc tương đương) | 3 |
| Có dấu hiệu hoạt động gần đây trong skills, workflows, state hoặc decisions | 3 |

## 5. Xếp hạng

- `0-39`: Stage 0 - Foundation
- `40-69`: Stage 1 - Built
- `70-89`: Stage 2 - Compounding
- `90-100`: Stage 3 - Autonomous

Label từng layer:
- `Strong`: >=20
- `Solid`: 15-19
- `Thin`: 8-14
- `Missing`: <8

Bar format: dùng `#` cho mỗi 5 điểm, ví dụ `####.` cho khoảng 20/25.

## 6. Top gaps theo leverage

Với mỗi tiêu chí mất điểm, tính:

`leverage = points_lost * impact_multiplier`

Impact multipliers:
- Không có RSS/news ingestion: `4x`
- Không có database persistence: `4x`
- Không có operating manual: `3x`
- Thiếu agent brains chính: `3x`
- Không có recurring workflow: `3x`
- Không có executable audit/guard: `2x`
- Không có Telegram delivery path: `2x`
- Không có state/memory artifact: `2x`
- Thiếu tests/golden dataset: `1.5x`
- Các gap khác: `1x`

Chọn top 3 gap có leverage cao nhất. Mỗi gap phải có một bước sửa cụ thể, ví dụ:
- "Thêm workflow trong `.github/workflows/scraper.yml` để chạy `python main.py --legacy` theo lịch."
- "Bổ sung env contract vào `.env.example` cho Telegram/LLM/Postgres."
- "Mở rộng `scripts/audit_agent.py` để kiểm tra source config và notifier path."

## 7. Output format

Trả trực tiếp bằng Markdown:

```markdown
# CryptoSentinel AIOS Audit - YYYY-MM-DD
**Score: N/100** (Stage X: Label)

## Scoreboard

Context       ####.  N/25  Label
Connections   ####.  N/25  Label
Capabilities  ####.  N/25  Label
Cadence       ####.  N/25  Label

## Strengths
- ...
- ...
- ...

## Top 3 Gaps (ranked by leverage)
1. **Gap name** (-N x multiplier)
   -> Concrete next step.
2. **Gap name** (-N x multiplier)
   -> Concrete next step.
3. **Gap name** (-N x multiplier)
   -> Concrete next step.

## Suggested next
One highest-leverage action.

---
Structural audit only. For content truthfulness, run the Auditor skill.
```

Sau khi in report, hỏi: "Bạn muốn mình lưu report này vào `audits/audit-YYYY-MM-DD.md` để theo dõi điểm theo thời gian không?"

## 8. Quy tắc vận hành
- Đọc nhanh, không sửa file trong quá trình audit.
- Không gọi database production nếu chỉ cần audit cấu trúc. Ưu tiên kiểm file, env contract và workflow.
- Nếu cần chạy lệnh, ưu tiên `python scripts/audit_agent.py` hoặc `pytest tests/unit` khi có test unit.
- Báo điểm trung thực, không nương tay. Điểm 90+ chỉ dành cho hệ có cadence tự động, connections đầy đủ, guard rõ và state vận hành thật.
