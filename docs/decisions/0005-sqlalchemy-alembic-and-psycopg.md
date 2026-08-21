# ADR-005: SQLAlchemy, Alembic và Psycopg cho persistence V1

## Status

Accepted

## Date

2026-08-21

## Context

ADR-003 đã khóa PostgreSQL làm system of record nhưng để mở ORM, migration library và driver. V1 cần mapping typed cho `Source`, `CrawlRun`, `RawJobSnapshot`, `Job`; migration có thể review; PostgreSQL 18 integration test thật; và command chạy được cả Windows local lẫn API container Python 3.13.

Hệ thống hiện là single-operator modular monolith. Chưa có bằng chứng cần async database stack, generic repository, connection-pool service hoặc tách persistence thành process riêng.

## Decision

- Dùng SQLAlchemy `2.0.52` theo Annotated Declarative (`DeclarativeBase`, `Mapped`, `mapped_column`) cho relational mapping.
- Dùng Alembic `1.19.1` cho versioned migration. `Base.metadata` là input autogenerate, nhưng mọi candidate migration phải được review và `alembic check` phải không còn drift trước khi merge.
- Dùng synchronous Psycopg `3.3.4` qua dialect `postgresql+psycopg://`.
- Dùng `psycopg[binary]` cho V1 local/container để có wheel self-contained trên Windows và slim image. Khi có public production deployment, đánh giá lại `psycopg[c]` hoặc image có system `libpq` theo security/update model của V6.
- Database URL chỉ lấy từ `DEVRADAR_DATABASE_URL`; không lưu credential trong `alembic.ini`.
- Migration là đường tạo schema. Application và test không dùng `Base.metadata.create_all()` thay migration.
- Giữ mapping theo module ownership: source/run/snapshot thuộc `ingestion`, canonical job thuộc `catalog`, metadata/config chung thuộc `platform`.
- V1 lưu bounded raw text trong PostgreSQL. `V1-004` phải enforce source-specific byte/content-type limit trước persistence; chưa thêm object storage khi chưa có size/retention evidence.
- Không thêm generic repository hoặc async abstraction trong quyết định này.

## Official-source basis

- [SQLAlchemy 2.0 Declarative table configuration](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html) mô tả `DeclarativeBase`, `Mapped` và `mapped_column`; `mapped_column()` là API ORM 2.x thay cho Declarative `Column` legacy style.
- [Alembic autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) yêu cầu đưa `Base.metadata` vào `target_metadata` và nhấn mạnh candidate migration phải được review thủ công.
- [SQLAlchemy PostgreSQL Psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg) định nghĩa URL `postgresql+psycopg://` cho Psycopg 3.
- [Psycopg installation guide](https://www.psycopg.org/psycopg3/docs/basic/install.html) ghi binary install là lựa chọn cho đa số user, hỗ trợ Python 3.10–3.14 và PostgreSQL 10–18; local C build được ưu tiên cho production site có toolchain phù hợp.

## Alternatives considered

### Psycopg + SQL migration viết tay, không SQLAlchemy ORM

Rejected. Alembic đã phụ thuộc SQLAlchemy; domain V1 có nhiều typed field, foreign key và constraint. Dùng SQL riêng cho mọi read/write trong khi vẫn giữ metadata migration sẽ tạo hai schema representation mà chưa giảm dependency thực tế.

### SQLModel

Rejected. V1 chưa cần gộp API schema với persistence model. Coupling đó làm ownership giữa API, ingestion và catalog kém rõ mà không giải quyết requirement hiện tại.

### Async SQLAlchemy/Psycopg

Rejected cho V1 vì chưa có measured concurrency bottleneck hoặc async database consumer. Sync transaction boundary nhỏ hơn và đủ cho migration, CLI ingestion cùng read API ban đầu.

### `psycopg[c]` ngay trong slim image

Deferred đến production hardening. Nó cần compiler, Python headers và `libpq-dev`, làm image/build phức tạp hơn; V1 local portfolio đã có supported binary wheel và hash-locked install.

## Consequences

### Positive

- schema, constraints và typed mapping dùng cùng metadata;
- migration có revision history, fresh-database check và drift detection;
- một synchronous transaction boundary đủ cho idempotent ingestion V1;
- không kéo dependency của phase sau.

### Trade-offs

- Alembic candidate vẫn cần human/agent review; autogenerate không chứng minh migration đúng;
- binary wheel đóng gói client library riêng, nên production hardening phải review update strategy;
- raw content trong PostgreSQL chỉ phù hợp khi fetch limit và retention được enforce/đo.

## Required follow-up

- `V1-004` enforce bounded payload trước khi tạo `RawJobSnapshot`.
- `V1-009` đặt snapshot + canonical Job upsert trong transaction rõ ràng.
- V6 review driver packaging cùng image scanning và managed database policy.
