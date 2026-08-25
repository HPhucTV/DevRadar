<div align="center">

# DevRadar

**Job Market Intelligence có provenance cho thị trường tuyển dụng IT Việt Nam.**

DevRadar biến job posting công khai thành dữ liệu có thể tìm kiếm, phân tích và đối chiếu — từ ingestion an toàn đến semantic search, CV matching và dashboard Việt/Anh.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16.3.2-111111?logo=nextdotjs&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

[Khám phá sản phẩm](#product-showcase) · [Kiến trúc](#architecture-at-a-glance) · [Chạy local](#quick-start) · [Tài liệu](#documentation)

</div>

---

## ✦ Trạng thái hiện tại

DevRadar đang ở trạng thái **implementation in progress** trong V6. Local workflow hiện có thể:

- nhận URL trang tuyển dụng qua một `SourceRecipe` generic, không cần người dùng viết adapter;
- chọn seniority, xem trước 3–5 job và ánh xạ field trực quan khi auto-detection chưa đủ tin cậy;
- chạy thủ công hoặc theo lịch cố định, theo dõi history/health và bảo vệ job khỏi false removal;
- khám phá job, analytics, CV matching và alert qua dashboard Việt/Anh.

Các số liệu dataset cũ được giữ trong evidence lịch sử, không hiển thị như bộ đếm realtime của sản phẩm.

<a id="product-showcase"></a>

## ◈ Product showcase

<p align="center">
  <img src="docs/assets/readme/devradar-product-poster.png" alt="DevRadar Source Recipe workflow từ URL đến preview và lịch crawl local" width="100%" />
</p>

<p align="center"><sub>UI local thật: dán URL, chọn seniority, kiểm tra preview và vận hành crawl có provenance.</sub></p>

## ◎ Why DevRadar

- **No-code ingestion:** một `SourceRecipe` generic cho URL owner chọn, với SSRF guard, bounded preview và visual mapping.
- **Market intelligence:** deterministic extraction, taxonomy, exact pgvector search và trend analytics có denominator.
- **Operator experience:** dashboard Việt/Anh, crawl history, source health, local CV matching và alert workflow.
- **Privacy by boundary:** không giữ file CV gốc mặc định, không log raw CV/secret và không dùng LLM production để thay workflow xác định.

<a id="architecture-at-a-glance"></a>

## ◇ Architecture at a glance

```mermaid
flowchart LR
    S["Owner-local SourceRecipe"] --> I["HTTP-first / isolated browser fallback"]
    I --> P[("PostgreSQL + pgvector")]
    P --> X["Deterministic intelligence"]
    X --> A["FastAPI /api/v1"]
    A --> W["Next.js dashboard"]
```

1. **Modular monolith:** một deployable system trước khi cân nhắc distributed infrastructure.
2. **Deterministic-first:** structured data và parser trước LLM fallback.
3. **Provenance-first:** mọi `Job` truy ngược được tới `Source`, `CrawlRun` và `RawJobSnapshot`.

Đọc data flow, module ownership và trust boundary đầy đủ trong [Architecture](docs/ARCHITECTURE.md).

## ◫ Tech stack

| Layer | Technology | Vai trò |
|---|---|---|
| Web | Next.js, React, TypeScript | Dashboard Việt/Anh và same-origin BFF |
| API | Python, FastAPI, Pydantic | REST JSON dưới `/api/v1` và OpenAPI contract |
| Data | PostgreSQL, pgvector, SQLAlchemy, Alembic | System of record, migration và exact vector search |
| Ingestion | Generic SourceRecipe, HTTP-first, Playwright fallback | Preview/mapping, raw snapshot và provenance |
| Runtime | Docker Compose | Local/protected topology và reproducible deployment surface |

<a id="quick-start"></a>

## ⚡ Quick Start

### Chạy một lần nhấp trên Windows

Yêu cầu duy nhất cho product runtime là Docker Desktop đã được cài đặt; không cần mở ứng dụng trước.
Clone repository, sau đó double-click:

```text
start-devradar.cmd
```

Nếu Docker engine chưa sẵn sàng, launcher tự mở Docker Desktop và chờ tối đa 180 giây. Launcher
không tự cài hoặc cập nhật Docker, không vượt màn hình license/login/update; khi timeout, cửa sổ giữ lại
thông báo để bạn mở Docker Desktop thủ công rồi chạy lại.

Sau khi Docker ready, launcher chỉ tạo `.env` từ `.env.example` khi file chưa tồn tại, build ba image,
migrate PostgreSQL, bật API/web/crawler worker trong localhost no-login mode, chạy smoke rồi mở dashboard.
Nó không tự enable hoặc crawl URL và không xóa volume. Workflow nằm tại
`http://127.0.0.1:3000/sources`.

### Chạy thủ công cho development

```powershell
git clone https://github.com/HPhucTV/DevRadar.git
cd DevRadar

python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes --requirement requirements-dev.lock

docker compose --env-file .env.example --profile crawler build api web crawler
docker compose --env-file .env.example up database --wait
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example --profile crawler up api web crawler --wait

Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
.\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
```

Mở `http://127.0.0.1:3000`. OpenAPI nằm tại `http://127.0.0.1:8000/docs`.

Các flow opt-in như local authentication, CV matching và DeepSeek synthetic evaluation được mô tả trong [Operations](docs/OPERATIONS.md) và [AI](docs/AI.md). Không thêm secret thật vào `.env.example` hoặc Git.

### Quality gates

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check

Set-Location web
npm run check
```

## ⌘ Project map

```text
DevRadar/
├── src/devradar/        # Domain, ingestion, intelligence, API và CLI
├── web/                 # Next.js dashboard
├── migrations/          # Alembic schema history
├── tests/               # Unit, contract và PostgreSQL integration tests
├── docs/                # Product, architecture, ADR, runbook và evidence
├── scripts/             # Smoke, deploy, backup, restore và security gates
├── start-devradar.cmd   # One-click local launcher cho Windows
├── compose.yaml         # Local API/web/database/crawler topology
└── AGENTS.md            # Working agreements cho human và AI agent
```

<a id="documentation"></a>

## 📚 Documentation

| Tài liệu | Nội dung |
|---|---|
| [Product](docs/PRODUCT.md) | Bài toán, người dùng, phạm vi và non-goals |
| [Architecture](docs/ARCHITECTURE.md) | Module boundary, data flow và topology |
| [Domain model](docs/DOMAIN_MODEL.md) | Ubiquitous language, entity và lifecycle |
| [Ingestion](docs/INGESTION.md) | Source Recipe, preview/mapping, normalization và change detection |
| [API](docs/API.md) | REST contract dưới `/api/v1` |
| [AI](docs/AI.md) | Deterministic-first, evaluation, privacy và cost boundary |
| [Operations](docs/OPERATIONS.md) | Test, security, deployment, backup và monitoring |
| [Roadmap](docs/ROADMAP.md) | Capability, exit criteria và evidence theo phase |
| [Architecture Decision Records](docs/decisions/README.md) | Các quyết định Accepted, Proposed và Superseded |

## 🛡 Safety boundary

- Runtime URL ingestion chỉ bật trong localhost bằng `DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED=true`.
- `terms_notice` luôn hiển thị cùng version/evidence. Owner có thể acknowledgement đúng version để tiếp tục local; thao tác này không phải legal certification.
- CAPTCHA, authentication, paywall, anti-bot hoặc access denial chuyển recipe sang `blocked`; hệ thống không cung cấp bypass.
- Mọi `Job` giữ provenance qua `CrawlRun` và `RawJobSnapshot`; `JobChange` chỉ chuyển `missing`/`removed` sau complete-run gates.
- Raw CV, secrets và PII không được ghi vào log/tracing; external AI không nhận dữ liệu nhạy cảm nếu chưa có explicit privacy configuration.

DevRadar hiện được chứng minh ở local/protected deployment boundary. Repository chưa tuyên bố public HTTPS/provider deployment đã hoàn tất.

---

<div align="center">
  <i>Data pipeline trước. Reasoning sau. Evidence luôn đi cùng claim.</i>
</div>
