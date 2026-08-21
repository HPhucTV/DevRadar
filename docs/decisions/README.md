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
| [ADR-007](0007-proposed-openai-first-v3-provider-and-pgvector.md) | Superseded | Lịch sử đề xuất OpenAI-first; bị ADR-008 thay thế |
| [ADR-008](0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md) | Accepted | DeepSeek V4 Pro generation spike synthetic-only; embedding tách quyết định |

## Candidate technology chưa được chấp nhận

Prefect đã được đánh giá và defer theo ADR-006; chỉ đánh giá lại khi có measured need. ADR-007 được giữ để truy vết nhưng đã `Superseded` bởi ADR-008. DeepSeek generation, embedding provider/pgvector và mọi công nghệ V4–V6 chỉ được `Accepted` sau khi phase gate xác minh compatibility, vận hành, chi phí và privacy; quyết định khó đảo ngược cần ADR mới hoặc amendment qua ADR kế tiếp, không âm thầm sửa lịch sử.
