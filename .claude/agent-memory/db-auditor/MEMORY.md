# Memory Index

- [Console cp1252 quirk](env-console-cp1252.md) — prefix `PYTHONIOENCODING=utf-8` to all diagnose scripts or they crash on unicode titles

- [Outbox baseline 2026-06-13](outbox-baseline-2026-06-13.md) — all 23 signals sent, zero expired/failed/pending, p95 lag 4s; DATABASE_URL requires explicit `source .env` in bash

> 2026-06-12: dự án pivot DEX-only — bảng `signals` thay `articles`; baseline outbox cũ đã xóa vì gắn với schema cũ.
