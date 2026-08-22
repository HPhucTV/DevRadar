# DevRadar

**DevRadar — Agentic Job Market Intelligence Platform** là dự án portfolio thu thập, chuẩn hóa và phân tích dữ liệu tuyển dụng IT công khai, ưu tiên thị trường Việt Nam. Hệ thống được phát triển theo nguyên tắc **data pipeline trước, Agent sau**: dữ liệu, provenance và tính đúng đắn phải ổn định trước khi thêm LLM hoặc agentic workflow.

## Trạng thái

| Thuộc tính | Giá trị |
|---|---|
| Trạng thái | `implementation` |
| Phase hiện tại | `v5` — Dashboard, CV matching và alerts (`proposed`); V4 đã `complete` |
| Mô hình sử dụng ban đầu | Portfolio cá nhân, single-operator |
| Thị trường ưu tiên | Job IT Việt Nam, nội dung Việt/Anh, lương VND |
| Code chạy được | Có — V1/V2 data pipeline và V3 intelligence; không có agent runtime hiện hành |

V1 đã hoàn tất safe fetch/snapshot pipeline, ba concrete source adapters, PostgreSQL persistence và REST API. V2 đã hoàn tất direct schedule/retry, JobChange lifecycle, source health/quarantine, operator enqueue và one-shot worker. V3 đã đóng với `3339` canonical jobs từ approved complete runs, semantic held-out gate đạt, `1003/3339` accepted deterministic extraction results, `3339/3339` current embeddings và analytics denominator/coverage có evidence. ADR-010 chấp nhận local `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 384d cùng exact pgvector; RemoteJobs.org là cohort remote thứ cấp, không đại diện cho claim thị trường Việt Nam. V4 đã đánh giá typed planner/validator/analyst proposal paths và LangGraph, nhưng cả ba reasoning path bị loại theo ADR-013 vì safe facts đã xác định outcome và không có measurable usefulness gain. Runtime hiện giữ deterministic V1–V3 paths; LangGraph và production model adapter tiếp tục bị defer.

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
    O["Deterministic scheduler - V2"] --> I
    L["LLM and pgvector - V3"] --> X
```

Các thành phần ghi kèm phiên bản chỉ được triển khai khi task/entry gate tương ứng đạt. ADR-010 hiện hành chấp nhận local multilingual MiniLM + exact pgvector cho V3 private deployment; external embedding provider, HNSW và công nghệ phase sau vẫn chưa được mở.

## Roadmap tóm tắt

| Phiên bản | Trọng tâm | Công nghệ/capability được mở |
|---|---|---|
| V1 | Crawler MVP và REST API | Python, FastAPI, PostgreSQL, Docker Compose |
| V2 | Automation và change detection | PostgreSQL-backed schedule/retry, crawl health |
| V3 | AI extraction và semantic search | LLM boundary, skill taxonomy, pgvector |
| V4 | Agentic decision evaluation | Hoàn tất evaluation; reasoning runtime bị loại, LangGraph deferred |
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
- [V4-001 design spec](docs/superpowers/specs/2026-08-22-v4-001-deterministic-baseline-tool-policy-design.md): typed decision, baseline metric và default-deny tool policy trước khi chọn graph.
- [V4-001 evidence](docs/evidence/V4-001-deterministic-agent-policy.md): TDD, policy matrix, deterministic failure gates và verification boundary.
- [V4-002 spike evidence](docs/evidence/V4-002-langgraph-direct-workflow-spike.md): exact-version footprint/recovery benchmark và direct-workflow decision.
- [V4-003 historical run safety evidence](docs/evidence/V4-003-agent-run-state-safety.md): typed limits/state, AgentRun migration, transaction/retry/concurrency/redaction và PostgreSQL gates đã được đánh giá trước removal.
- [V4-004 historical planner/validator evidence](docs/evidence/V4-004-planner-validator-direct-workflow.md): safe responsibility facts, direct proposal/validation/application và failure gates của runtime thử nghiệm.
- [V4-005 historical analyst evidence](docs/evidence/V4-005-analyst-skill-trend.md): safe aggregate projection, exact publication gates và PostgreSQL integration của runtime thử nghiệm.
- [Operations](docs/OPERATIONS.md): test, security, observability, retention, CI/CD và deployment gates.
- [Source discovery](docs/sources/SHORTLIST.md): evidence và approval outcome; VNG, NAVER Vietnam/Greenhouse và MoMo đã được duyệt cho bounded Vietnam scope, RemoteJobs.org được duyệt riêng cho V3 remote cohort có attribution, GeoComply/Lever vẫn `permission_required`.
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
- [V1 live inventory evidence](docs/evidence/V1-013-live-inventory.md): ba complete source runs, current-version replay và 78-job inventory snapshot.
- [V1 closeout evidence](docs/evidence/V1-closeout.md): product decision về dataset gate, exit-criteria mapping và chuyển phase sang V2.
- [V2 Prefect spike evidence](docs/evidence/V2-001-prefect-spike.md): compatibility, retry/schedule, footprint và quyết định defer Prefect.
- [V2 direct orchestration evidence](docs/evidence/V2-002-direct-orchestration.md): PostgreSQL claim/idempotency, scheduled slot và transient-only retry.
- [V2 lifecycle evidence](docs/evidence/V2-003-job-change-and-absence-lifecycle.md): meaningful changes, two-run removal, false-removal guard và reactivation.
- [V2 source health evidence](docs/evidence/V2-004-source-health-and-quarantine.md): inventory baseline/anomaly, quarantine, operator recovery và safe API view.
- [V2 operator API evidence](docs/evidence/V2-005-operator-api-and-history.md): fail-closed write gate, idempotent pending runs, JobChange history và negative trust-boundary tests.
- [V2 closeout evidence](docs/evidence/V2-006-v2-closeout.md): one-shot worker, five scheduled acceptance cycles, exit-criteria mapping và chuyển phase sang V3.
- [V3 evaluation evidence](docs/evidence/V3-001-evaluation-dataset-and-baseline.md): versioned synthetic split, deterministic baseline, hallucination gap và release targets.
- [V3 provider/pgvector spike](docs/evidence/V3-002-provider-privacy-cost-pgvector-spike.md): official-doc comparison, cost/privacy model, pgvector micro-benchmark và live development/held-out gate evidence.
- [V3 extraction/cache evidence](docs/evidence/V3-003-extraction-result-cache.md): accepted-only cache, deterministic-first orchestration và PostgreSQL transaction semantics.
- [V3 taxonomy evidence](docs/evidence/V3-004-taxonomy-classification-summary.md): versioned skill category, role classification và bounded evidence-rendered summary.
- [V3 embeddings/search/trends evidence](docs/evidence/V3-005-embeddings-search-trends.md): fixed local model integrity, pgvector persistence, semantic filters và analytics denominator/coverage.
- [V3 closeout evidence](docs/evidence/V3-006-v3-closeout.md): approved inventory `3339`, frozen semantic held-out, extraction/backfill coverage, API/DB/static gates và phase handoff.
- [DeepSeek V3 spike module](src/devradar/intelligence/deepseek_spike.py): synthetic-only, fail-closed JSON extraction spike; không phải production provider adapter.
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

### V3 DeepSeek synthetic spike (opt-in)

Module này chỉ gửi 4 case `development` synthetic đã khóa; không gửi JD nguồn thật hoặc CV. Key đã dán trong chat phải revoke/rotate trước. Cách đơn giản nhất là tự tạo `.env.local` tại root repository với đúng một dòng:

```dotenv
DEVRADAR_DEEPSEEK_API_KEY=YOUR_NEW_ROTATED_KEY
```

`.env.local` đã bị Git và Docker ignore; không sửa `.env.example` và không gửi nội dung file qua chat. Environment variable hiện hữu được ưu tiên hơn file. Chạy spike từ root repository:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
try {
    .venv\Scripts\python -m devradar.intelligence.deepseek_spike
} finally {
    Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
}
```

Khi chạy phải lưu lại chỉ model/fingerprint, usage, latency, cost và validation summary, không lưu prompt/output. Xóa `.env.local` sau spike nếu không còn cần dùng local.

Sau khi prompt/schema đã khóa, release evaluation held-out chạy riêng bằng:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
try {
    .venv\Scripts\python -m devradar.intelligence.deepseek_spike --release-held-out
} finally {
    Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
}
```

### V3 local embeddings

Model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` chỉ được tải từ artifact ONNX/revision đã khóa; inference không tự download và không gửi JD/query ra external provider. Lần đầu local có thể tải khoảng 240 MiB. Sau khi PostgreSQL Compose đang chạy và migration đã lên `head`, tải model rồi backfill một batch bounded:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:DEVRADAR_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/devradar'
try {
    .venv\Scripts\python -m devradar.cli download-embedding-model
    .venv\Scripts\python -m alembic upgrade head
    .venv\Scripts\python -m devradar.cli embed-jobs --max-items 100
} finally {
    Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:\DEVRADAR_DATABASE_URL -ErrorAction SilentlyContinue
}
```

`--max-items` nhận `1..1000`; rerun cùng Job/hash/model là idempotent. Có thể đặt `DEVRADAR_EMBEDDING_MODEL_PATH` cho một thư mục local khác, nhưng model identity/revision/hash không thay đổi. Docker image đã prefetch đúng artifact revision vào image build; semantic API trả `503` an toàn nếu artifact thiếu hoặc sai hash.

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

Khi local operator đã bật write gate và enqueue một run qua API, xử lý tối đa một pending request ngoài HTTP lifecycle bằng:

```powershell
docker compose --env-file .env.example --profile crawler run --rm crawler work-one --deadline-minutes 60
```

Queue rỗng trả `{"processed": false}` và exit `0`. Command này có thể gọi network nếu có pending run hợp lệ; nó chỉ resolve source từ allow-list đã duyệt và không nhận URL tùy ý.

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
