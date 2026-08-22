# V5-001 — Next.js UX slice và scaffold

**Status:** `complete` ngày 2026-08-22. V5 vẫn `in_progress`; V5-002 nối data views.

## Design và boundary

- Next.js `16.3.2` App Router nằm trong `web/`, tách khỏi Python `src/`.
- React `19.2.8`, TypeScript `5.9.3`, ESLint `9.39.5` và `eslint-config-next@16.3.2` được pin exact.
- Sáu route được manifest hóa: `/`, `/jobs`, `/jobs/[jobId]`, `/analytics`, `/crawler-health`, `/cv-match`.
- V5-001 không tạo BFF/Route Handler, API client, auth, CV upload, fake data hoặc public environment variable.
- `web/AGENTS.md` và `web/CLAUDE.md` được Next.js sinh tự động; `next-env.d.ts` được Next cập nhật theo build.

Official sources used:

- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation): Node `20.9+`, App Router, TypeScript/ESLint và command surface.
- [Project structure](https://nextjs.org/docs/app/getting-started/project-structure): `src` folder, route groups và file-system routes.
- [Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components): Server Component mặc định, client boundary chỉ khi có state/event/browser API.
- [Dynamic segments](https://nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes): `[jobId]` và async `params`.
- [ESLint config](https://nextjs.org/docs/app/api-reference/config/eslint): flat config/core-web-vitals; Next 16 dùng ESLint CLI, không `next lint`.

## TDD và verification

RED trước manifest:

```text
Error: ENOENT: no such file or directory, open 'web/src/contracts/routes.json'
```

GREEN sau manifest/pages:

```text
✔ route manifest owns the exact V5-001 surface
ℹ pass 1
```

Frontend `npm run check` sau scaffold:

```text
route manifest: 1 passed
eslint: pass
tsc --noEmit: pass
next build: pass
```

Next build liệt kê `/`, `/analytics`, `/crawler-health`, `/cv-match`, `/jobs`, dynamic `/jobs/[jobId]` và không có `/api` Route Handler. `npm audit --audit-level=high` báo `found 0 vulnerabilities`.

## HTTP smoke

Dev server bind `127.0.0.1:3000`; API local chạy ở `127.0.0.1:8000` trên PostgreSQL Compose thật. Sáu route trả `200`:

```text
/=200
/jobs=200
/jobs/<real-job-id>=200
/analytics=200
/crawler-health=200
/cv-match=200
```

`GET /api/v1/jobs` trả `3339` canonical jobs, `/sources` trả `4` sources và `/skills` trả `23` tracked skills trong inventory local. Filter `/jobs?query=python` và detail với ID thật render thành công.

## Chưa triển khai

- Job/analytics/crawler views hiện chỉ là truthful placeholders ở V5-001; V5-002 là task nối API thật.
- CV match route giữ trạng thái `backend_not_ready`; upload/profile/match thuộc V5-003–005.
- Không có auth, alert, BFF, browser E2E hoặc public deployment.

