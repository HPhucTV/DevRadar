# V5-002 — Dashboard, job explorer, analytics và crawler health

**Status:** `complete` ngày 2026-08-22. V5 vẫn `in_progress`; V5-003 là task kế tiếp.

## Kết quả

- Server-only `web/src/lib/api.ts` gọi trực tiếp FastAPI dưới `/api/v1` bằng `fetch` `cache: no-store`.
- Backend response/error được kiểm tra envelope tối thiểu; HTTP lỗi, invalid JSON, invalid contract và network failure đều về safe `ApiFailure`.
- Overview hiển thị số source/job/skill, coverage và latest canonical jobs.
- `/jobs` hỗ trợ GET literal filters `query`, `location`, page-based pagination và link tới detail.
- `/jobs/[jobId]` gọi detail + change history, hiển thị description/provenance và empty/error state.
- `/analytics` gọi `/skills` và `/skill-trends`, giữ cohort/analyzed/coverage/denominator trong UI.
- `/crawler-health` gọi `/sources` và `/crawl-runs`, phân biệt health/coverage/status; partial/failed run không đổi thành removal.
- Shared `loading.tsx` và `error.tsx` bao phủ dashboard route group; empty states không bịa dữ liệu.

Next.js Server Components là default; không tạo BFF/Route Handler hoặc expose `NEXT_PUBLIC_*`. `DEVRADAR_API_BASE_URL` chỉ đọc ở server.

## Verification

```text
web npm run check: route manifest 1 passed; ESLint pass; TypeScript pass; Next build pass
backend default pytest: 177 passed, 29 skipped
PostgreSQL API smoke: health=ok, jobs=2/3339, sources=4/4, skills=3/23
frontend HTTP smoke: six route responses 200; filtered jobs and real job detail 200
```

## Boundary

- Không thêm schema library, data-fetch library, chart dependency hoặc UI kit.
- API client không nhận URL từ browser; base URL chỉ từ server environment/default local.
- UI không hiển thị raw error payload, secret, raw snapshot hoặc CV content.
- CV upload/matching/alerts/auth vẫn là V5-003–006.

