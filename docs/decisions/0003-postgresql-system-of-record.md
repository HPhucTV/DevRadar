# ADR-003: PostgreSQL là system of record

## Status

Accepted

## Date

2026-08-21

## Context

DevRadar có dữ liệu quan hệ và transaction rõ: source, run, snapshot, canonical job, change, skill, match và audit. Hệ thống cần upsert/idempotency, constraint, query/filter và lịch sử nhất quán. V3 dự kiến semantic search nhưng không cần một vector database riêng ở quy mô portfolio.

## Decision

- Dùng PostgreSQL làm authoritative system of record từ V1.
- Upsert Job, observation/last-seen và JobChange phải giữ transaction consistency.
- Raw snapshot metadata/provenance thuộc PostgreSQL; cách lưu bounded payload vật lý được quyết định trong V1 scaffold dựa trên kích thước và retention.
- pgvector là candidate V3, chỉ bật sau embedding spike/evaluation. Vector index/cache không trở thành nguồn authoritative.
- ORM/migration library không được khóa bởi ADR này; V1 scaffold phải chọn giải pháp tương thích FastAPI/PostgreSQL và chứng minh migration/test workflow.

## Alternatives considered

### SQLite làm database chính

Rejected vì production-like portfolio cần PostgreSQL behavior, concurrent process/migration và pgvector path. SQLite có thể dùng cho tool nhỏ nhưng không được dùng để gọi test là PostgreSQL integration.

### Document database

Rejected vì domain có relationship, uniqueness, transaction và aggregate query rõ; schema linh hoạt không bù chi phí consistency/query.

### PostgreSQL cộng external vector database từ đầu

Rejected vì V1 chưa có embedding và V3 chưa có bằng chứng PostgreSQL/pgvector không đủ. Một datastore nữa làm tăng sync, secret, backup và failure mode.

### Chỉ lưu raw JSON

Rejected vì filter, dedup, lifecycle và trend cần canonical relational fields, constraint và provenance có cấu trúc.

## Consequences

### Positive

- một transaction boundary cho ingestion/change history;
- constraint/query/index phù hợp API và analytics;
- có đường nâng cấp pgvector mà không thêm datastore ngay;
- backup/migration/restore có một system of record rõ.

### Trade-offs

- local development cần PostgreSQL/Docker thay vì database embedded;
- schema và migration phải được review cẩn thận;
- raw payload lớn có thể cần storage strategy khác sau khi đo size/retention.

### Required follow-up

- V1 scaffold tạo migration cho domain tối thiểu và integration test trên PostgreSQL thật.
- V3 benchmark pgvector trên dataset/query thực trước khi chọn index hoặc external vector store.
- Mọi đề xuất datastore khác phải mô tả ownership, consistency, backup và rebuild path từ PostgreSQL.

