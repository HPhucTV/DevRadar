# V2-004 — Source health, anomaly và quarantine

## Kết quả

Source health hiện được tính deterministically từ persisted CrawlRun history. Inventory anomaly được đánh giá trước absence lifecycle, nên một run “technically succeeded” nhưng coverage đáng ngờ không thể gây false removal.

## Policy đã implement

- baseline là median của tối đa năm complete successful run gần nhất;
- inventory-drop gate chỉ bật sau tối thiểu hai baseline run;
- current `items_found < 50%` baseline làm coverage thành `incomplete`, Source `degraded`, reason/run signal `inventory_drop_anomaly`;
- complete run hợp lệ cập nhật baseline, reset failure và phục hồi `healthy`;
- policy/safety failure quarantine ngay;
- transient failure chuyển `degraded`, từ ba failure liên tiếp chuyển `unhealthy`, không quarantine như lỗi dữ liệu;
- platform failure chuyển `unhealthy`;
- data/layout failure đầu chuyển `degraded`, lần liên tiếp thứ hai quarantine;
- scheduled/retry trigger bị chặn khi quarantined; manual operator run vẫn được phép để kiểm tra và chỉ complete success mới phục hồi.

PostgreSQL giữ `consecutive_failures`, `baseline_items_found`, `health_reason_code`, `quarantined_at` trên Source và `health_signal_code` trên CrawlRun. Constraint khóa non-negative baseline/failure và yêu cầu `quarantined_at` đúng theo health status.

## PostgreSQL acceptance scenarios

### Inventory anomaly và recovery

1. hai complete run, mỗi run `10` items, tạo baseline `10`;
2. run tiếp theo chỉ `2` items: status vẫn `succeeded` nhưng coverage bị hạ `incomplete`;
3. `items_missing=0`, `items_removed=0`, toàn bộ 10 Job vẫn `active`;
4. `last_success_at` không thay đổi bởi anomaly run;
5. complete run đủ 10 items tiếp theo tạo `source_recovered`, reset failure và health `healthy`.

### Quarantine và operator recovery

1. manual run fail `policy_blocked` làm Source `quarantined` ngay;
2. scheduled run bị `source_quarantined` trước `adapter.discover()`; adapter call count bằng `0`;
3. manual complete run được phép, phục hồi `healthy`, xóa reason/quarantine timestamp và reset failure.

### Operator view

`GET /api/v1/sources`/`{sourceId}` trả health status, consecutive failure, safe reason; detail trả baseline và quarantine timestamp. Rate policy, allowed hosts và secret vẫn không lộ qua response/OpenAPI.

Không scenario nào chạm source/network thật.

## Verification

Ngày 2026-08-21 trên Python `3.13.14`, PostgreSQL `18.6`:

```text
python -m pytest                              119 passed
python -m ruff check .                        All checks passed
python -m ruff format --check .               100 files already formatted
python -m mypy                                no issues in 53 source files
python -m pip check                           No broken requirements found
python -m alembic check                       No new upgrade operations detected
```
