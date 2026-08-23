# ADR-018: Không thêm Redis/worker pool sau V6 benchmark

## Status

Accepted

## Date

2026-08-23

## Context

V6 cần đo queue pressure trước khi quyết định thêm Redis hoặc distributed worker. Current product là
single-operator portfolio; crawl source dùng concurrency 1 theo policy, operator queue nằm trong
PostgreSQL và `FOR UPDATE SKIP LOCKED` đã đảm bảo claim atomic/idempotent.

Benchmark synthetic trên PostgreSQL 18.6 local tạo 100 source/run độc lập để không vi phạm one-active-run
per source, rồi claim bằng 1/4/8 thread với cùng query/transaction pattern. Nó đo claim/control-plane,
không giả vờ đo network crawl, parser hoặc provider throughput.

## Decision

- Giữ PostgreSQL-backed pending run queue và one-shot worker hiện hành.
- Không thêm Redis, Celery/RQ, daemon worker pool hoặc distributed lease ở V6.
- Current release target dùng tối đa một crawler process cho mỗi approved source; source policy vẫn
  `concurrency=1` và external scheduler gọi `work-one` bounded.
- Đánh giá lại khi có ít nhất một measured trigger: pending queue age vượt 10 phút trong 3 cycle,
  PostgreSQL claim p95 vượt 250 ms, claim throughput dưới 20/s, cần hơn một deployment node, hoặc stale
  running-run recovery trở thành incident lặp lại.

## Benchmark evidence

| Workers | Rows | Throughput/s | p50 claim | p95 claim | Max claim |
|---:|---:|---:|---:|---:|---:|
| 1 | 100 | 77.473 | 11.603 ms | 15.284 ms | 34.545 ms |
| 4 | 100 | 214.946 | 14.160 ms | 20.360 ms | 59.946 ms |
| 8 | 100 | 197.763 | 30.527 ms | 66.884 ms | 88.577 ms |

4 workers đạt throughput tốt nhất; 8 workers tăng latency mà không tăng throughput. Nhu cầu thực tế một
crawler/source nhỏ hơn rất xa mức benchmark, nên distributed queue không có measured value.

## Alternatives considered

### Redis + Celery/RQ

Rejected vì tạo thêm system of record/monitoring/retry semantics mà không giải quyết bottleneck đo được.

### Process-local in-memory queue

Rejected vì mất pending state khi restart và làm yếu PostgreSQL idempotency/provenance hiện có.

### Tăng source concurrency

Rejected vì source policy/rate limit không cho phép và throughput crawl bị external/network bound, không
phải claim query.

## Consequences

- Runtime topology giữ lean, một persistence/control-plane và ít secret/failure mode hơn.
- Pending/running state vẫn query được trong PostgreSQL và existing one-shot worker không đổi.
- Nếu trigger đánh giá lại xuất hiện, ADR mới phải đo queue age, recovery, duplicate prevention và source
  rate policy trước khi chọn distributed infrastructure.
