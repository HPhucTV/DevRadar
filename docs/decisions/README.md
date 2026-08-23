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
| [ADR-009](0009-accept-local-multilingual-e5-and-pgvector.md) | Superseded | Historical local multilingual E5 baseline; thay bởi ADR-010 |
| [ADR-010](0010-accept-fastembed-minilm-semantic-remediation.md) | Accepted | FastEmbed multilingual MiniLM 384d + exact pgvector sau semantic remediation |
| [ADR-011](0011-accept-secondary-remote-api-cohort.md) | Accepted | Cohort remote thứ cấp cho V3 scale gate |
| [ADR-012](0012-accept-direct-v4-agent-workflow-defer-langgraph.md) | Superseded in part | Historical direct V4 workflow spike; quyết định defer LangGraph vẫn còn hiệu lực |
| [ADR-013](0013-remove-unretained-v4-agent-runtime.md) | Accepted | Loại V4 agent runtime không có measurable usefulness; giữ deterministic paths |
| [ADR-014](0014-accept-discord-webhook-alert-connector.md) | Accepted | Discord webhook là connector alert V5 đầu tiên |
| [ADR-015](0015-accept-v6-authentication-strategy.md) | Accepted | V6 dùng server-side session-based authentication với PostgreSQL session record |
| [ADR-016](0016-accept-reproducible-ci-deploy-rollback.md) | Accepted | Reproducible CI, forward-compatible migration và application image rollback |
| [ADR-017](0017-accept-postgresql-backup-restore-and-bounded-monitor.md) | Accepted | PostgreSQL custom backup/restore drill và monitor bounded không thêm metrics backend |
| [ADR-018](0018-do-not-add-redis-worker-pool-after-v6-benchmark.md) | Accepted | Giữ PostgreSQL queue/one-shot worker; Redis/worker pool không có measured need |
| [ADR-019](0019-accept-pinned-trivy-container-gate.md) | Accepted | Pinned Trivy scan riêng cho API/crawler; gate fail nếu còn fixed HIGH/CRITICAL |
| [ADR-020](0020-accept-nextjs-standalone-web-compose-artifact.md) | Accepted | Next.js standalone web image tham gia Compose deploy/rollback và three-image scan |

## Candidate technology chưa được chấp nhận

Prefect đã được đánh giá và defer theo ADR-006; chỉ đánh giá lại khi có measured need. ADR-007 được giữ để truy vết nhưng đã `Superseded` bởi ADR-008. ADR-010 hiện hành chấp nhận local multilingual MiniLM + exact pgvector cho V3 private deployment. ADR-012 vẫn hoãn LangGraph; ADR-013 loại direct V4 agent runtime vì không có measurable usefulness gain, nên hiện không có agent runtime được chấp nhận. ADR-015 khóa auth strategy cho V6-002 nhưng chưa phải implementation evidence. ADR-016 khóa CI/deploy/rollback boundary; ADR-019 đã thay scanner container bằng Trivy pinned, còn ADR-020 mở rộng release/scan sang standalone web artifact. Public deployment/restore vẫn cần phase gate riêng. External embedding provider, HNSW và mọi công nghệ V5–V6 vẫn cần phase gate/evidence riêng. Quyết định khó đảo ngược cần ADR mới hoặc amendment qua ADR kế tiếp, không âm thầm sửa lịch sử.
