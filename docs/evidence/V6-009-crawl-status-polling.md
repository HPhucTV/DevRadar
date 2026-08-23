# V6-009 — Crawl status polling

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `Done` — vertical slice đã đi qua contract, implementation, regression, integration và browser smoke.

## Delivered

- UI `/crawler-health` giữ `CrawlRun.id` sau `POST` `202` và polling đúng detail resource mỗi 2 giây.
- Polling dừng khi `succeeded|partial|failed|cancelled`, khi backend lỗi hoặc sau 30 giây; timer được cleanup khi component unmount.
- BFF mới `GET /api/devradar/crawl-runs/{runId}` forward tới FastAPI `GET /api/v1/crawl-runs/{runId}` với cùng session cookie, CSRF/origin và response budget.
- Không chạy crawler/network trong HTTP request; worker vẫn là CLI `devradar work-one` hiện hành theo ADR-018.

## Regression found and fixed

Browser smoke ban đầu dùng `GET /crawl-runs?pageSize=20` để tìm run đang poll. Khi history có hơn 20 row,
pending run không còn trong trang đầu và UI báo sai `Crawl history refreshed; the requested run is no longer visible.`
Test contract đã tái hiện boundary này. Polling được chuyển sang detail endpoint theo `runId`, nên không phụ thuộc
pagination của history.

## Verification

```text
RED: npm test --prefix web → polling test fail trước implementation.
GREEN: npm test --prefix web → 11 passed.
npm run check --prefix web → test/lint/typecheck/build pass.
  Build route inventory gồm ƒ /api/devradar/crawl-runs/[runId].
PostgreSQL worker acceptance:
  DEVRADAR_TEST_DATABASE_URL=... pytest -m postgresql tests/integration/test_ingestion_runner.py
  -k pending_api_run_is_claimed_once_and_retried_outside_http → 1 passed, 8 deselected.
```

### Browser smoke

- Authenticated operator session trên `http://127.0.0.1:3001` với API auth/operator-write bật.
- Source registry: 4 source; operator chỉ trigger source approved bằng `sourceId` và idempotency key.
- Trigger cuối: run `3e892473-fe77-458b-8ff9-a551beff509a` nhận `202 pending`.
- One-shot fixture worker ngoài HTTP claim run và finalize `succeeded/incomplete`, `items_found=1`,
  `health_signal_code=inventory_drop_anomaly` trong khoảng 0.3 giây.
- UI tự đổi notice thành `Crawl succeeded.` và history hiển thị `succeeded · incomplete`.
- Screenshot: [v6-009-crawl-status-polling.png](../../output/playwright/v6-009-crawl-status-polling.png) (artifact Git-ignored).
- Live bounded worker smoke trước đó cũng hoàn tất VNG `succeeded/complete` với 27 item và MoMo
  `succeeded/complete` với 37 item; cả hai lâu hơn cửa sổ 30 giây nên UI timeout an toàn và yêu cầu refresh,
  không chuyển timeout thành failure.

## Boundary and residual risk

- Polling chỉ là read-after-enqueue UX; operator hoặc scheduler vẫn phải gọi CLI worker. Không có daemon,
  Redis, distributed lease hoặc API endpoint chạy network.
- 30 giây là giới hạn UI có chủ đích. Run lâu hơn vẫn tồn tại trong PostgreSQL và có thể đọc qua refresh/detail;
  timeout không tạo `missing/removed` và không thay đổi run state.
- Fixture worker chứng minh fast terminal transition/UI contract; không phải claim về live source completeness.
- V6-004, V6-005 và V6-007 vẫn `In Progress`; slice này không cung cấp HTTPS public, managed secret provider,
  remote CI hay off-host backup evidence.
