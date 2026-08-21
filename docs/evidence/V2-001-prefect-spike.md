# V2-001 — Prefect compatibility và orchestration spike

## Kết luận

Prefect `3.8.3` tương thích stack hiện tại và cung cấp retry/schedule đúng capability, nhưng không được chọn cho V2. Với ba source, local portfolio và single-operator, dependency footprint cùng control-plane/process overhead lớn hơn giá trị hiện tại. [ADR-006](../decisions/0006-defer-prefect-use-direct-v2-orchestration.md) chấp nhận PostgreSQL-backed direct orchestration.

Spike chỉ dùng virtual environment và database trong `%TEMP%`; không sửa lockfile/dependency của repository và không crawl source thật.

## Môi trường

| Thuộc tính | Giá trị |
|---|---|
| Thời điểm | 2026-08-21, Asia/Saigon |
| OS | Windows AMD64 |
| Python | `3.13.14` |
| Prefect | `3.8.3`, API `0.8.4` |
| Pydantic trong spike | `2.13.4` |
| Prefect database | SQLite `3.50.4` trong temp |
| Stack repo kiểm tra compatibility | FastAPI `0.141.1`, SQLAlchemy `2.0.52`, Psycopg `3.3.4` |

`pip check` kết thúc với `No broken requirements found`.

## Dependency footprint

Checkpoint ngay sau cài đặt ghi nhận:

- virtual environment: `365,205,680` bytes;
- 86 distribution ngoài runtime lock hiện tại;
- package footprint tăng khoảng `187,320,234` bytes;
- dependency transitively kéo thêm Redis client, asyncpg, Docker client, telemetry, notification và cryptography packages dù V2 chưa cần các capability đó.

Sau scheduled/server spike, toàn temp root tăng lên `428,710,061` bytes do Prefect database/WAL và runtime artifacts. Không artifact nào được đưa vào Git.

## Retry spike

Hai task dùng `retries=2` và cùng condition chỉ retry `TransientSpikeError`:

| Scenario | Kết quả |
|---|---|
| Transient fail hai lần | attempt thứ ba complete và trả `recovered` |
| Policy exception | đúng một attempt; condition từ chối retry |
| Cold direct flow + ephemeral server | `93.606s` |
| Lần hai dùng cùng ephemeral database | `27.204s` |

Capability phù hợp yêu cầu transient-only retry, nhưng thời gian cold start và API/database lifecycle là overhead đáng kể so với direct in-process policy.

## Schedule và self-hosted server spike

- Self-hosted server trên `127.0.0.1:14200` cùng `flow.serve(interval=5, limit=1)` chạy được sau khi server healthy.
- Lần khởi động đầu gặp readiness race và `ConnectError` khi serve process kết nối trước server.
- Python server + serve processes dùng khoảng `359 MB` working set, chưa tính PowerShell wrapper.
- Ba empty flow run complete; nhiều scheduled run bị skip vì subprocess startup/capacity, và còn một pending run khi shutdown.
- `Ctrl+C` với `pause_on_shutdown=True` pause deployment như documented, nhưng serve process kết thúc `1` sau interrupted subprocess.
- Server shutdown ghi nhận SQLite `database is locked` trong flow-run state transition trước khi dừng.

Port `14200` đã được xác nhận đóng sau cleanup. Temp artifacts được giữ ngoài repository để có thể điều tra lại trong phiên local và không phải product artifact.

## Official references

- [Install Prefect](https://docs.prefect.io/v3/get-started/install): Python support, full/minimal install và yêu cầu API server.
- [Run flows in local processes](https://docs.prefect.io/v3/how-to-guides/deployment_infra/run-flows-in-local-processes): long-running serve process, subprocess execution, schedule và pause-on-shutdown behavior.
- [Workflow retries](https://docs.prefect.io/v3/how-to-guides/workflows/retries): retry count, delay, condition và jitter capability.
- [Run a local Prefect server](https://docs.prefect.io/v3/how-to-guides/self-hosted/server-cli): self-hosted local server topology.

## Decision gate

| Gate | Outcome |
|---|---|
| Python/stack compatibility | Pass |
| Transient-only bounded retry | Pass |
| Scheduled execution | Pass với operational caveats |
| Dependency/runtime proportionality | Fail cho current scope |
| Single-operator deployment simplicity | Fail so với direct orchestration |
| Repository dependency mutation | Không thực hiện |

V2-001 hoàn tất với quyết định defer Prefect. Không coi các spike flow rỗng là V2 scheduled acceptance evidence; V2-006 phải dùng DevRadar ingestion workflow và PostgreSQL history thật.
