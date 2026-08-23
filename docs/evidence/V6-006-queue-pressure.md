# V6-006 — Queue pressure và Redis/worker decision

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `Done`

## Scope và method

`scripts/benchmark_queue.py` chạy trên disposable migrated PostgreSQL 18.6. Harness tạo 100 source/run
độc lập, dùng unique benchmark principal và claim đúng query shape `status=pending`, ordered,
`FOR UPDATE SKIP LOCKED`, short commit. Nó không gọi network, source adapter, LLM hoặc alert connector.

Harness lần đầu dùng chung principal nên hai benchmark parallel claim lẫn rows; harness đã được sửa để
isolate mỗi run bằng principal riêng và ba result cuối chạy tuần tự. Kết quả lỗi không được dùng làm evidence.

## Kết quả cuối

| Workers | Claimed | Total | Throughput/s | p50 | p95 | Max |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100/100 | 1290.769 ms | 77.473 | 11.603 ms | 15.284 ms | 34.545 ms |
| 4 | 100/100 | 465.233 ms | 214.946 | 14.160 ms | 20.360 ms | 59.946 ms |
| 8 | 100/100 | 505.656 ms | 197.763 | 30.527 ms | 66.884 ms | 88.577 ms |

Không còn pending benchmark row sau mỗi run và source/run synthetic được cleanup. 4 workers nhanh hơn 8;
current one-worker/source workload nằm xa bottleneck.

## Decision

[ADR-018](../decisions/0018-do-not-add-redis-worker-pool-after-v6-benchmark.md) giữ PostgreSQL queue và
one-shot worker. Không thêm Redis, queue service, daemon pool hoặc distributed lease. Revisit chỉ theo
measured queue-age/claim-latency/throughput/multi-node/stale-run incident triggers trong ADR.

## Boundary

Benchmark chỉ đo database claim/control-plane, không đo external crawl throughput. Source concurrency vẫn
1; không dùng benchmark này để tăng request rate hoặc bypass source approval/rate-limit.
