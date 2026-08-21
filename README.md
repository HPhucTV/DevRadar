# DevRadar

**DevRadar — Agentic Job Market Intelligence Platform** là dự án portfolio thu thập, chuẩn hóa và phân tích dữ liệu tuyển dụng IT công khai, ưu tiên thị trường Việt Nam. Hệ thống được phát triển theo nguyên tắc **data pipeline trước, Agent sau**: dữ liệu, provenance và tính đúng đắn phải ổn định trước khi thêm LLM hoặc agentic workflow.

## Trạng thái

| Thuộc tính | Giá trị |
|---|---|
| Trạng thái | `implementation` |
| Phase hiện tại | `v1` — Crawler MVP và REST API (`in_progress`) |
| Mô hình sử dụng ban đầu | Portfolio cá nhân, single-operator |
| Thị trường ưu tiên | Job IT Việt Nam, nội dung Việt/Anh, lương VND |
| Code chạy được | Có — ba source adapters, snapshot persistence, idempotent Job upsert, sáu read-only domain endpoints và structured JSON events |

Repository đã có FastAPI scaffold tối thiểu, dependency lock, PostgreSQL schema/migration cho bốn entity V1, approved source registry, typed adapter contract, safe HTTPS fetcher, raw snapshot persistence, deterministic normalization/canonical hash, ba concrete source adapters, transactional current-state Job upsert, read-only Job/Source/CrawlRun API, safe structured observability và operator CLI cho on-demand ingestion. Integration test chạy PostgreSQL thật; API cùng browser crawler có Docker Compose local đã kiểm chứng. Dataset/exit gate cuối V1 vẫn chưa hoàn tất.

## Mục tiêu

DevRadar hướng tới các khả năng sau:

- thu thập job định kỳ từ các nguồn công khai đã được phê duyệt;
- lưu raw snapshot có provenance và chuẩn hóa dữ liệu job;
- xử lý idempotency, deduplication và change detection;
- trích xuất skill bằng deterministic parser trước, LLM fallback sau;
- phân tích xu hướng kỹ năng và semantic search;
- so khớp CV với job mà vẫn bảo vệ dữ liệu cá nhân;
- dùng agent cho các quyết định cần reasoning, không dùng agent để thay thế workflow xác định;
- cung cấp dashboard, alert và bằng chứng vận hành đủ tốt cho một portfolio kỹ thuật.

## Nguyên tắc thiết kế

1. **Data pipeline trước, Agent sau.** V1–V2 tập trung vào ingestion và khả năng vận hành; AI bắt đầu ở V3, agentic workflow ở V4.
2. **Modular monolith trước.** Chỉ tách service hoặc thêm hạ tầng phân tán khi có nhu cầu đã đo được.
3. **Nguồn hợp lệ mới được crawl.** Không bypass CAPTCHA, authentication, anti-bot hoặc điều khoản truy cập.
4. **Provenance không được mất.** Mọi dữ liệu chuẩn hóa phải truy ngược được về source, URL, thời điểm fetch và raw snapshot.
5. **Deterministic-first.** JSON-LD, selector và parser được ưu tiên trước LLM; kết quả AI luôn phải qua schema validation.
6. **Không tuyên bố nhiều hơn bằng chứng.** Trạng thái roadmap chỉ được nâng khi có test, metric hoặc demo artifact tương ứng.

## Kiến trúc định hướng

```mermaid
flowchart LR
    S["Approved public sources"] --> I["Ingestion modules"]
    I --> P[("PostgreSQL")]
    P --> A["FastAPI /api/v1"]
    P --> X["Analytics and matching"]
    X --> A
    A --> W["Next.js dashboard - V5"]
    O["Prefect - V2"] --> I
    L["LLM and pgvector - V3"] --> X
    G["LangGraph - V4"] --> I
    G --> X
```

Các thành phần ghi kèm phiên bản chưa thuộc V1. Kiến trúc và dependency được kích hoạt theo phase, không được cài sẵn chỉ vì có trong tầm nhìn dài hạn.

## Roadmap tóm tắt

| Phiên bản | Trọng tâm | Công nghệ/capability được mở |
|---|---|---|
| V1 | Crawler MVP và REST API | Python, FastAPI, PostgreSQL, Docker Compose |
| V2 | Automation và change detection | Prefect, retry, crawl health |
| V3 | AI extraction và semantic search | LLM boundary, skill taxonomy, pgvector |
| V4 | Agentic decision layer | LangGraph cho planner/validator/analyst |
| V5 | Trải nghiệm người dùng | Next.js, dashboard, CV matching |
| V6 | Production hardening | Auth, rate limit, CI/CD, monitoring; Redis chỉ khi có bằng chứng cần |

Chi tiết về prerequisite, non-goal, exit criteria và demo evidence nằm trong [Roadmap](docs/ROADMAP.md).

## Tài liệu

- [Product specification](docs/PRODUCT.md): bài toán, người dùng, phạm vi và yêu cầu.
- [Architecture](docs/ARCHITECTURE.md): module boundary, data flow, trust boundary và topology theo phase.
- [Domain model](docs/DOMAIN_MODEL.md): ubiquitous language, entity và lifecycle.
- [Ingestion](docs/INGESTION.md): source approval, crawler contract, normalization, deduplication và change detection.
- [API](docs/API.md): REST contract dưới `/api/v1` và phase availability.
- [AI](docs/AI.md): deterministic-first, evaluation, agent boundary, chi phí và quyền riêng tư.
- [Operations](docs/OPERATIONS.md): test, security, observability, retention, CI/CD và deployment gates.
- [Source discovery](docs/sources/SHORTLIST.md): evidence và approval outcome; VNG, NAVER Vietnam/Greenhouse và MoMo đã được duyệt cho bounded local non-commercial scope, GeoComply/Lever vẫn `permission_required`.
- [Pre-V1 local evidence](docs/evidence/PRE-007-local-prerequisites.md): Docker/PostgreSQL capability và constraint đã xác minh.
- [V1 scaffold evidence](docs/evidence/V1-001-scaffold.md): clean install, test/static gates, live API và Docker Compose smoke.
- [V1 PostgreSQL evidence](docs/evidence/V1-002-postgresql-schema.md): schema invariants, fresh migration, integration test và container migration smoke.
- [V1 source registry evidence](docs/evidence/V1-003-source-registry.md): active allow-list, typed adapter contract và fail-closed resolution.
- [V1 safe fetch/snapshot evidence](docs/evidence/V1-004-safe-fetch-and-snapshot.md): pinned DNS/IP transport, SSRF/redirect/size controls, caller-owned transaction và bounded live smoke.
- [V1 normalization evidence](docs/evidence/V1-005-normalization-and-hashing.md): raw-preserving normalization fixtures, false-inference guards và versioned canonical hash.
- [V1 NAVER/Greenhouse adapter evidence](docs/evidence/V1-006-naver-greenhouse-adapter.md): one-request full-list discovery, deterministic parsing, coverage guards và bounded live smoke.
- [V1 VNG adapter evidence](docs/evidence/V1-007-vng-adapter.md): server-confirmed IT group filters, complete pagination, contact redaction và bounded live smoke.
- [V1 MoMo adapter evidence](docs/evidence/V1-008-momo-adapter.md): public-UI pagination, browser trust boundary, deterministic detail parsing và on-demand live evidence.
- [V1 Job upsert evidence](docs/evidence/V1-009-job-upsert.md): source-scoped identity, replay/stale protection, current-state update và caller-owned rollback.
- [V1 read API evidence](docs/evidence/V1-010-read-api.md): PostgreSQL-backed pagination/filter/sort, OpenAPI, safe error và data-exposure contract.
- [V1 observability evidence](docs/evidence/V1-011-observability.md): JSON request/error/domain events, correlation, log-derived metrics và redaction boundary.
- [V1 Compose/runner evidence](docs/evidence/V1-012-compose-and-runner.md): on-demand ingestion, containerized Chromium sandbox, PostgreSQL/API smoke và full quality gates.
- [Roadmap](docs/ROADMAP.md): kế hoạch V1–V6 và definition of done.
- [Architecture Decision Records](docs/decisions/README.md): quyết định đã chấp nhận và quyết định còn đề xuất.
- [Ý tưởng ban đầu](DevRadar_Agentic_Job_Market_Intelligence.md): tài liệu tham khảo gốc, không phải bằng chứng trạng thái triển khai.

## Quick Start

Các lệnh dưới đây đã được kiểm chứng bằng Windows PowerShell, Python 3.13, Docker Engine 29.1.3 và Docker Compose 2.40.3.

### Local development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes --requirement requirements-dev.lock
.venv\Scripts\python -m uvicorn devradar.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

Mở `http://127.0.0.1:8000/docs` hoặc kiểm tra process health ở `http://127.0.0.1:8000/api/v1/health`. Dừng development server bằng `Ctrl+C`.

Chỉ khi chạy MoMo adapter local, cài Chromium đúng version Playwright đã khóa:

```powershell
.venv\Scripts\python -m playwright install chromium
```

### Quality gates

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
```

PostgreSQL integration là opt-in và tạo/xóa database test tên ngẫu nhiên. Với database Compose đang chạy:

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

### Docker Compose local

```powershell
docker compose --env-file .env.example build api
docker compose --env-file .env.example up database --wait
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example up api --wait
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
docker compose --env-file .env.example down
```

API bind tại `127.0.0.1:8000`; PostgreSQL bind tại `127.0.0.1:55432`. `docker compose down` giữ named volume. Chỉ xóa volume khi operator chủ động chấp nhận mất dữ liệu local.

Migration phải chạy trước application feature dùng database. Health hiện vẫn là process liveness, không phải database readiness; PostgreSQL integration evidence được kiểm tra riêng.

Bounded live crawl là thao tác explicit có network và ghi PostgreSQL; chỉ chạy source đang `approved`. `--max-items` giới hạn số item được xử lý và cố ý ghi coverage `incomplete`:

```powershell
docker compose --env-file .env.example --profile crawler run --rm crawler crawl --source naver-vietnam-greenhouse --max-items 1 --deadline-minutes 10
```

Các source key V1 hợp lệ là `naver-vietnam-greenhouse`, `vng-careers` và `momo-careers`. Browser chỉ được launch qua service `crawler`: non-root, read-only filesystem, Chromium sandbox và seccomp profile pin theo Playwright `1.62.0`. API service không được dùng như browser runtime. Network-level egress enforcement chưa được tuyên bố; source adapter vẫn fail closed bằng host/IP/route allow-list.

## Nguồn sự thật

- Roadmap xác định phase hiện tại và điều kiện hoàn thành.
- ADR `Accepted` giải thích các quyết định khó đảo ngược.
- Các tài liệu domain/API/ingestion là contract thiết kế trước khi có code.
- Sau khi FastAPI tồn tại, OpenAPI sinh từ code là nguồn sự thật cho wire contract; thay đổi phải đồng bộ tài liệu trong cùng thay đổi.
- Tài liệu ý tưởng ban đầu giữ vai trò tầm nhìn, không được dùng để kết luận một feature đã được triển khai.
