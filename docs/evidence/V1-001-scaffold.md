# V1-001 — FastAPI scaffold và verified command surface

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** FastAPI process health/OpenAPI, dependency lock, unit/static gates và Docker Compose local. Không gồm schema, migration, database application integration, source registry hoặc crawler.

## 1. Stack đã khóa

| Thành phần | Version / image |
|---|---|
| Python local | `3.13.14` |
| Python image | `python:3.13.15-slim-bookworm` |
| FastAPI | `0.141.1` |
| Starlette | `1.6.0` |
| Uvicorn | `0.52.4` |
| PostgreSQL image/runtime | `postgres:18.6-alpine3.24` / `18.6` |
| pytest | `9.1.1` |
| HTTP test client | `httpx2 2.9.1` |
| Ruff | `0.16.4` |
| mypy | `2.3.1` |
| Docker / Compose | `29.1.3` / `2.40.3-desktop.1` |

Runtime và dev dependency được tách trong `requirements.in`/`requirements-dev.in`; lock files pin transitive version và artifact hashes. Docker cài runtime lock bằng `--require-hashes`.

## 2. Official-source decisions

- [FastAPI bigger applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) cho package + `APIRouter` module boundary.
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/) cho `TestClient`/pytest pattern.
- [Starlette current TestClient source](https://github.com/Kludex/starlette/blob/main/starlette/testclient.py) yêu cầu ưu tiên `httpx2`; runtime warning với legacy `httpx` được xử lý bằng `httpx2==2.9.1`.
- [FastAPI container guide](https://fastapi.tiangolo.com/deployment/docker/) cho app image/process layout.
- [Python official image tags](https://hub.docker.com/_/python) và [PostgreSQL official image](https://hub.docker.com/_/postgres) cho exact supported tags. PostgreSQL 18 volume mount dùng `/var/lib/postgresql` theo official image change.
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/) cho root `pyproject.toml` và Python target.

FastAPI tutorial tại thời điểm kiểm tra vẫn ghi legacy `httpx`, nhưng installed Starlette `1.6.0` phát deprecation warning và upstream source đã chuyển sang `httpx2`. Runtime evidence + current Starlette source được ưu tiên; test cuối không còn warning.

## 3. Clean local verification

Environment generator bị xóa bằng `python -m venv --clear .venv`, sau đó cài lại chỉ từ `requirements-dev.lock` với hash enforcement.

| Gate | Kết quả |
|---|---|
| clean `pip install --require-hashes` | Pass |
| `pytest` | `2 passed`, không warning |
| `ruff check .` | Pass |
| `ruff format --check .` | 30 files formatted |
| `mypy` strict | 6 source files, no issues |
| `pip check` | No broken requirements |
| local Uvicorn health | HTTP 200, `data.status=ok` |
| local OpenAPI | title `DevRadar API`, version `0.1.0`, health path present |

## 4. Docker Compose verification

`docker compose --env-file .env.example up --build --wait` đã build và start thành công:

- API healthy tại `127.0.0.1:8000`, chạy UID `999`, filesystem read-only, all capabilities dropped và `no-new-privileges`;
- PostgreSQL healthy tại `127.0.0.1:55432`, query trả server version `18.6`;
- runtime container `pip check` pass;
- `GET /api/v1/health` trả HTTP 200;
- cả hai host port chỉ bind loopback.

`docker compose --env-file .env.example down` đã remove container/network, giải phóng port `8000/55432` và giữ named volume `devradar_postgres-data`. Không chạy volume deletion.

## 5. Boundary còn mở

- Health là process liveness, không kiểm tra database/source readiness.
- Chưa có migration command; `V1-002` phải chọn ORM/migration stack và chứng minh PostgreSQL integration thật.
- Chưa có jobs/sources/crawl-runs endpoint; chúng thuộc `V1-010`.
- Chưa có crawler/browser dependency trong runtime lock; source adapter task chỉ thêm dependency đã được spike/chứng minh cần.
- Chưa có CI workflow; CI/CD vẫn theo phase/task roadmap.
