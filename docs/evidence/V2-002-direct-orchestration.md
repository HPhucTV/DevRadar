# V2-002 — Direct schedule, retry và run orchestration

## Kết quả

V2 dùng cùng ingestion use case cho manual, scheduled và retry trigger, với PostgreSQL giữ idempotency/coordination. Không thêm dependency, control plane, Redis hoặc worker service.

## Implementation

- `crawl_runs.trigger_key` định danh trigger; partial unique index `(source_id, trigger_key)` ngăn cùng source/slot được tạo hai lần.
- partial unique index theo `source_id` khi status `pending|running` đảm bảo tối đa một active run mỗi source.
- `scheduled_for` lưu UTC slot của scheduled trigger; slot/key được tạo deterministically từ source key và approved interval.
- retry dùng `retry_of_run_id`, `attempt_number` và unique relation để không tạo nhánh retry trùng.
- `retry_after_seconds` bị database constraint giới hạn `0..3600`.
- retry policy tối đa ba attempt tổng cộng, exponential backoff có bounded jitter, tôn trọng bounded `Retry-After` và chỉ nhận `dns_failure`, `network_error`, `network_timeout`, `rate_limited`, `server_error`.
- CLI `crawl` gọi orchestrator chung; optional `--idempotency-key` cho operator retry an toàn.

Migration `5c31b949ea7a` upgrade từ V1 và downgrade về base qua schema integration test; `alembic check` báo `No new upgrade operations detected`.

## PostgreSQL scenarios

Fixture orchestration chạy cùng adapter/runner/persistence thật nhưng không chạm network:

| Scenario | Evidence |
|---|---|
| Scheduled transient chain | attempt `1` scheduled fail `network_timeout`, attempt `2` retry fail `server_error`, attempt `3` retry success |
| Backoff/Retry-After | sleeper nhận `7s`, rồi `4s`; test không sleep thật |
| Retry provenance | attempt `2 → 1`, `3 → 2`; đúng ba persisted CrawlRun |
| Duplicate schedule slot | trả lại chain đã persist, `reused=true`, adapter `0` call, run/job count không tăng |
| Policy failure | `policy_blocked` tạo đúng một run, không sleep/retry |
| Concurrent source claim | active run khác trigger làm request mới fail `run_already_active` trước adapter call |
| Job idempotency | retry chain success tạo đúng một canonical Job |

Không chạy scheduled live crawl. Ba source hiện chỉ được approve cho bounded local on-demand scope; schedule engine được kiểm chứng bằng fixture cho tới khi source scope được re-review.

## Verification

Ngày 2026-08-21 trên Python `3.13.14`, PostgreSQL `18.6`:

```text
python -m pytest                              116 passed
python -m ruff check .                        All checks passed
python -m ruff format --check .               94 files already formatted
python -m mypy                                no issues in 51 source files
python -m pip check                           No broken requirements found
python -m alembic check                       No new upgrade operations detected
```

Test mặc định vẫn không chạm network. PostgreSQL tests tạo database riêng, migrate và drop sau mỗi case.
