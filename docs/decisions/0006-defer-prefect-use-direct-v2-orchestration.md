# ADR-006: Hoãn Prefect và dùng orchestration trực tiếp cho V2

## Status

Accepted

## Date

2026-08-21

## Context

V2 cần schedule ingestion, retry có kiểm soát, chống double-processing và lưu run history cho ba source trong mô hình portfolio single-operator. ADR-001 cho phép đánh giá Prefect từ V2 nhưng không chấp nhận dependency trước khi có compatibility, deployment và cost evidence.

Spike Prefect `3.8.3` trên Python `3.13.14` chứng minh flow retry và local schedule hoạt động, nhưng cũng tạo 86 distribution bổ sung, khoảng 187 MB package footprint, API server/database riêng và long-running serve process. Self-hosted schedule ngắn còn bộc lộ readiness race, capacity skip, shutdown process exit `1` và SQLite `database is locked`. Chi tiết nằm trong [V2-001 evidence](../evidence/V2-001-prefect-spike.md).

DevRadar chưa có measured requirement về distributed worker, remote orchestration UI, multi-operator control plane hoặc queue throughput. PostgreSQL đã là system of record và đủ để phối hợp một ingestion owner tại mỗi thời điểm.

## Decision

- Không thêm Prefect vào dependency hoặc runtime topology V2.
- V2 dùng orchestration xác định trong modular monolith: manual/API/scheduled trigger gọi cùng application use case; PostgreSQL giữ run, idempotency và coordination state.
- Scheduler chỉ tạo due run từ cấu hình source đã duyệt. Nó không nhận URL, adapter path, header hoặc secret tùy ý.
- Mỗi source chỉ có tối đa một active run. Duplicate trigger phải trả lại hoặc bỏ qua run đã được claim thay vì chạy ingestion lần hai.
- Retry tối đa ba attempt tổng cộng, chỉ cho lỗi được phân loại transient; tôn trọng bounded `Retry-After` và dùng exponential backoff có jitter. Lỗi policy, validation, parser contract hoặc source quarantine không được retry tự động.
- Không thêm Redis, queue, worker service hay orchestration database thứ hai trong V2.
- Prefect chỉ được đánh giá lại bằng ADR mới khi có nhu cầu đo được như nhiều worker/process host, backlog/throughput không đáp ứng, remote operations hoặc workflow topology mà direct orchestration không còn đủ.

## Official-source basis

- [Prefect installation](https://docs.prefect.io/v3/get-started/install) ghi full package cần API server từ Prefect Cloud hoặc self-hosted; operator self-hosted chịu trách nhiệm scaling, authentication và authorization.
- [Run flows in local processes](https://docs.prefect.io/v3/how-to-guides/deployment_infra/run-flows-in-local-processes) ghi `flow.serve()` là long-running process, chạy work trong subprocess riêng và mặc định pause schedule khi shutdown.
- [Prefect retries](https://docs.prefect.io/v3/how-to-guides/workflows/retries) hỗ trợ retry count, delay và condition; spike xác nhận capability này nhưng DevRadar có thể thực hiện policy bounded hiện tại trực tiếp.

## Alternatives considered

### Self-hosted Prefect trong V2

Rejected cho scope hiện tại. Capability hoạt động nhưng thêm control plane, database, process lifecycle và dependency surface lớn hơn nhu cầu ba source single-operator. Spike còn cho thấy shutdown/readiness/capacity behavior cần hardening riêng.

### Prefect Cloud

Rejected cho V2. Managed control plane giảm self-host operations nhưng thêm external dependency, account/credential, privacy và availability boundary khi current requirement chỉ là local portfolio automation.

### Redis queue và worker riêng

Rejected. Không có backlog, concurrency hoặc throughput measurement cho thấy PostgreSQL coordination cùng một scheduler/runner process không đủ.

## Consequences

### Positive

- không tăng dependency/runtime surface sau một spike không chứng minh lợi ích tương xứng;
- run history, claim và idempotency ở cùng PostgreSQL transaction boundary với ingestion metadata;
- manual, API và schedule dùng cùng deterministic use case và error taxonomy;
- topology local giữ nhỏ, dễ test và phù hợp single-operator.

### Trade-offs

- DevRadar tự sở hữu bounded retry, schedule polling và stale-claim recovery;
- chưa có Prefect UI, remote deployment control hoặc distributed work pool;
- scheduler process phải được giám sát bằng health/run evidence của chính DevRadar.

## Required follow-up

- `V2-002` implement PostgreSQL claim/idempotency, due schedule và transient-only retry.
- `V2-004` expose source/scheduler health đủ để phát hiện stalled hoặc quarantined source.
- V6 chỉ đánh giá Redis/worker hoặc orchestration framework khi benchmark queue pressure chứng minh nhu cầu.
