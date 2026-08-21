# Architecture Decision Records

ADR ghi lại **vì sao** một quyết định khó đảo ngược được chọn. Không xóa ADR cũ khi quyết định thay đổi; tạo ADR mới, tham chiếu và chuyển ADR cũ sang `Superseded` hoặc `Deprecated`.

## Lifecycle

```text
Proposed → Accepted → Superseded | Deprecated
```

- `Proposed`: đang được đánh giá, chưa cho phép implementation mặc định.
- `Accepted`: là ràng buộc hiện hành.
- `Superseded`: đã được ADR mới thay thế nhưng vẫn giữ lịch sử.
- `Deprecated`: không còn được dùng và chưa có quyết định thay thế trực tiếp.

## Decision index

| ADR | Trạng thái | Quyết định |
|---|---|---|
| [ADR-001](0001-modular-monolith-and-phase-gated-stack.md) | Accepted | Modular monolith và kích hoạt stack theo phase |
| [ADR-002](0002-data-pipeline-before-ai.md) | Accepted | Data pipeline trước AI/agentic workflow |
| [ADR-003](0003-postgresql-system-of-record.md) | Accepted | PostgreSQL là system of record |
| [ADR-004](0004-approved-source-allow-list.md) | Accepted | Chỉ crawl source đã duyệt qua allow-list |
| [ADR-005](0005-sqlalchemy-alembic-and-psycopg.md) | Accepted | SQLAlchemy, Alembic và Psycopg cho persistence V1 |
| [ADR-006](0006-defer-prefect-use-direct-v2-orchestration.md) | Accepted | Hoãn Prefect; V2 dùng PostgreSQL-backed direct orchestration |

## Candidate technology chưa được chấp nhận

Prefect đã được đánh giá và defer theo ADR-006; chỉ đánh giá lại khi có measured need. pgvector/LLM provider (V3), LangGraph (V4), Next.js/notification connector (V5), authentication strategy và Redis/worker topology (V6) vẫn là `Proposed`. Khi phase bắt đầu, spike phải xác minh compatibility, vận hành và chi phí; quyết định khó đảo ngược cần ADR mới hoặc amendment qua ADR kế tiếp, không âm thầm sửa lịch sử các ADR trên.
