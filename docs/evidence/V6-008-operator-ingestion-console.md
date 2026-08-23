# V6-008 — Operator ingestion console

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `Done` — vertical slice đã đi qua contract, implementation, web build và browser smoke.

## Delivered

- Same-origin BFF routes:
  - `GET /api/devradar/sources`;
  - `GET /api/devradar/crawl-runs`;
  - `POST /api/devradar/crawl-runs`.
- POST boundary chỉ chấp nhận một `sourceId` UUID, thêm `Content-Type: application/json`,
  `Idempotency-Key` (client-provided hoặc UUID server-generated), cookie session, CSRF và Origin.
- Extra `url`, `adapterKey`, `allowedHosts` hoặc field khác bị reject trước backend với
  `422 ingestion_request_invalid`.
- UI `/crawler-health` có operator session state, explicit `Load registry`/`Refresh`, source health
  metrics, approved-source-only `Run now`, pending crawl history và safe loading/error/empty states.
- Không render source URL, allowed hosts, rate policy, raw error, webhook hoặc arbitrary crawl input.

## Verification

```text
npm test: 9 passed
npm run check: test/lint/typecheck/build pass
Python PostgreSQL auth marker: 4 passed
Browser login: browser_operator session authenticated
Browser Load registry: 4 sources, 4 healthy, 18 historical runs rendered
Browser Run now (VNG Careers): status notice, new pending/unknown CrawlRun, 202 path proven
Browser malicious payload ({sourceId,url}): 422 ingestion_request_invalid
Browser screenshot: output/playwright/v6-008-crawler-health.png
```

## Boundary and safety evidence

- Existing FastAPI operator dependency still enforces auth role, CSRF/Origin, source approval,
  active-run conflict and idempotency; the browser cannot override any of these policies.
- The request only creates a pending row. Crawl network work remains in the existing bounded worker path.
- A real regression found during browser smoke (BFF omitted JSON `Content-Type`) was reproduced as
  `422 model_attributes_type`, covered by a route test, fixed, and re-verified as a pending `202` flow.
