# V5-001 Next.js UX slice và scaffold — Design Spec

**Ngày:** 2026-08-22  
**Trạng thái:** Đã được user ủy quyền quyết định và xác nhận tiếp tục  
**Phase:** V5 — Dashboard, CV matching và alerts

## Mục tiêu

V5-001 khóa information architecture, mapping sang FastAPI contract và tạo một Next.js scaffold build được cho sáu route portfolio. Task không implement dashboard data view, CV upload/matching, alert, authentication hoặc backend-for-frontend.

Scaffold phải trung thực: không hiển thị metric/job/CV giả, không gọi network khi test/build và ghi rõ capability nào thuộc V5-002 trở đi.

## Context đã xác minh

- Repository chưa có `package.json` hoặc frontend lockfile.
- Local runtime là Node `24.11.1`, npm `11.6.2`.
- npm registry snapshot ngày 2026-08-22: Next `16.3.2`, React/React DOM `19.2.8`, ESLint `10.9.0`, `eslint-config-next` `16.3.2`, TypeScript 5 stable `5.9.3`.
- Current FastAPI/OpenAPI đã có Job, JobChange, Source, CrawlRun, skill frequency/trend và health endpoint; ResumeProfile/JobMatch backend chưa tồn tại.
- V4 agent runtime đã bị loại; frontend không tạo route, card hoặc API client cho AgentRun.

Official framework basis:

- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation): App Router, TypeScript/ESLint setup, Node minimum `20.9`, scripts và root layout requirement.
- [Project structure](https://nextjs.org/docs/app/getting-started/project-structure): `src` folder, route group, private colocation và page-based public route rules.
- [Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components): layouts/pages là Server Components mặc định; Client Components chỉ cho state/event/browser APIs.
- [Dynamic segments](https://nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes): `[jobId]` và `params: Promise<{ jobId: string }>`.
- [ESLint config](https://nextjs.org/docs/app/api-reference/config/eslint): ESLint flat config, `core-web-vitals` và TypeScript configs; Next 16 không còn `next lint`.
- [Next CLI](https://nextjs.org/docs/app/api-reference/cli/next): `dev/build/start` và explicit `--hostname`; default bind là `0.0.0.0` nên local scripts phải dùng `127.0.0.1`.
- [Backend for Frontend guide](https://nextjs.org/docs/app/guides/backend-for-frontend): Server Components đọc data trực tiếp từ source thay vì gọi Route Handler trung gian.
- [Environment variables](https://nextjs.org/docs/pages/guides/environment-variables): biến không có prefix `NEXT_PUBLIC_` chỉ ở server; public-prefixed values bị inline vào browser bundle.

## Các hướng đã cân nhắc

### 1. Next.js ở repository root

Rejected. `package.json`, `src/app` và Node config sẽ trộn với Python `src/devradar`, làm command/file ownership khó đọc và tăng khả năng tooling quét nhầm.

### 2. Next.js trong `web/`, gọi FastAPI trực tiếp từ Server Components

Accepted. `web/` là presentation boundary rõ trong cùng modular monolith repository. Next route không trở thành backend service mới; FastAPI/OpenAPI vẫn là data contract duy nhất.

### 3. Next.js trong `web/` cùng Route Handler/BFF proxy

Rejected. V5-001 chưa có browser-only credential/CORS requirement buộc phải proxy. BFF sẽ lặp error/pagination/auth contract và tạo thêm public surface trước khi có consumer.

## Package và command surface

Runtime dependency exact:

- `next@16.3.2`;
- `react@19.2.8`;
- `react-dom@19.2.8`.

Development dependency exact:

- `typescript@5.9.3`;
- `eslint@10.9.0`;
- `eslint-config-next@16.3.2`;
- `@types/react@19.2.18`;
- `@types/react-dom@19.2.4`;
- `@types/node@24.13.3` để khớp major runtime được kiểm chứng.

Không thêm Tailwind, CSS-in-JS, UI kit, icon library, animation, state manager, data-fetch library, schema library, test framework hoặc OpenAPI generator. Native CSS, React/Next và Node built-in test runner đủ cho scaffold.

`web/package-lock.json` là lockfile duy nhất của frontend. Scripts:

- `npm run dev`: bind `127.0.0.1:3000`;
- `npm run build`;
- `npm run start`: bind `127.0.0.1:3000`;
- `npm run test`: Node built-in contract test, không network;
- `npm run lint`: ESLint CLI;
- `npm run typecheck`: `tsc --noEmit`;
- `npm run check`: test → lint → typecheck → build.

## Route và data contract

Một file `web/src/contracts/routes.json` là UX route manifest dùng đồng thời bởi shell và Node contract test. Mỗi entry có `id`, `path`, `pageFile`, `label`, `description`, `availability`, `showInNav` và exact `apiResources`.

| Route | Mục đích | FastAPI resource khi nối data | Availability sau V5-001 |
|---|---|---|---|
| `/` | overview portfolio | `GET /health`, `/jobs`, `/sources`, `/skills` | scaffolded; data ở V5-002 |
| `/jobs` | explorer/filter/pagination | `GET /jobs` | scaffolded; data ở V5-002 |
| `/jobs/[jobId]` | detail/provenance/change history | `GET /jobs/{jobId}`, `/jobs/{jobId}/changes` | scaffolded; data ở V5-002 |
| `/analytics` | skill frequency/trend với denominator | `GET /skills`, `/skill-trends` | scaffolded; data ở V5-002 |
| `/crawler-health` | source health và crawl history | `GET /sources`, `/crawl-runs` | scaffolded; data ở V5-002 |
| `/cv-match` | entry point cho secure CV flow | chưa có endpoint implemented | `backend_not_ready`; V5-003/004 |

Endpoint trong JSON dùng full path dưới `/api/v1` và HTTP method. Dynamic placeholder giữ camelCase `jobId` như OpenAPI. Detail route không nằm trong primary navigation.

V5-001 không tạo TypeScript copy của toàn OpenAPI schema. Khi V5-002 có consumer thật, data boundary phải chọn minimal runtime validation/generation dựa trên current OpenAPI và update `docs/API.md` nếu contract đổi. Không đoán ResumeProfile/JobMatch wire shape trước V5-003/004.

## Component và page structure

```text
web/
  src/
    app/
      (dashboard)/
        analytics/page.tsx
        crawler-health/page.tsx
        cv-match/page.tsx
        jobs/[jobId]/page.tsx
        jobs/page.tsx
        layout.tsx
        page.tsx
      globals.css
      layout.tsx
    components/
      app-shell.tsx
      route-placeholder.tsx
    contracts/
      routes.json
  tests/
    routes.test.mjs
```

- Root layout khai báo Vietnamese document language và metadata, không có client boundary.
- Dashboard layout dùng `AppShell`; navigation sinh từ manifest và `next/link`.
- `RoutePlaceholder` render heading, description, truthful availability và resource list; không tạo fake KPI/card/chart.
- Dynamic Job detail await `params` theo Next 16 contract và chỉ render opaque `jobId` đã encode như text; chưa fetch.
- Native CSS cung cấp readable light/dark tokens, responsive navigation, visible focus và `prefers-reduced-motion`; không cố hoàn thiện visual system của V5-002.

## Data và security boundary cho V5-002

- `DEVRADAR_API_BASE_URL` là server-only; không dùng `NEXT_PUBLIC_`.
- Default/example local URL là `http://127.0.0.1:8000`; URL validation và fetch implementation thuộc V5-002.
- Server Components gọi FastAPI trực tiếp, không vòng qua Next Route Handler.
- API response vẫn là untrusted boundary: V5-002 phải validate status/envelope trước render và không expose raw error/secret.
- CV match route không upload, giữ file hoặc gọi endpoint; nó chỉ nêu backend chưa sẵn sàng.
- Scaffold build/test không cần FastAPI/PostgreSQL/network.

## TDD và verification

RED đầu tiên là Node contract test được tạo trước `routes.json`; test phải fail vì manifest chưa tồn tại. GREEN chỉ đạt khi:

- exact sáu route/availability/API mapping khớp;
- path/id/pageFile unique;
- mọi `pageFile` tồn tại;
- navigation không chứa dynamic detail;
- CV match không claim backend endpoint.

Sau GREEN chạy `npm run check`. Next production build phải liệt kê đủ static routes và dynamic `/jobs/[jobId]`; không có `/api/*` Route Handler. Sau đó chạy backend default regression, Markdown link scan và Git diff check.

## Definition of Done

- Design/route/data contract được commit và không mâu thuẫn OpenAPI hiện hành.
- `web/` có exact pinned dependency/lock, App Router, TypeScript và ESLint flat config.
- Sáu truthful route scaffold build được; không fake data hoặc future backend behavior.
- Node contract test đã quan sát RED→GREEN.
- `npm run check` và backend default pytest pass; command được ghi vào README/AGENTS chỉ sau khi kiểm chứng.
- Không thêm BFF, Tailwind/UI kit/state/data library, public env, Docker topology hoặc API/migration change.
- Evidence ghi exact versions, commands, route build output, official sources và boundary chưa implement.
- Local board chuyển V5-001 `Done`, V5-002 `Ready`; V5 vẫn `in_progress`.

