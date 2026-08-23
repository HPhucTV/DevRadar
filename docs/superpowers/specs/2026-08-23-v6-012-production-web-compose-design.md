# V6-012 — Production web Compose design

**Trạng thái:** Accepted
**Ngày:** 2026-08-23

## Mục tiêu

Biến dashboard Next.js thành production artifact có thể deploy/rollback cùng FastAPI trong topology
Docker Compose hiện hành. Sau task này, repository cung cấp đầy đủ API + web + PostgreSQL command surface;
external provider chỉ còn chịu trách nhiệm host, HTTPS termination, managed secrets và off-host services.

## Gap hiện tại

- Root `Dockerfile`, Compose, deploy/rollback và smoke chỉ bao phủ FastAPI.
- `web/` build được nhưng không có Dockerfile/service/health check hoặc container scan.
- BFF đã dùng server-only `DEVRADAR_API_BASE_URL`, nên một web container có thể gọi API qua Compose DNS;
  browser không cần gọi API origin trực tiếp.
- Public V6 không thể gọi là end-to-end nếu dashboard chưa nằm trong deploy/rollback artifact set.

## Lựa chọn

1. **Next standalone container trong Compose — chọn.** Khớp single-host modular monolith, giữ BFF và toàn
   bộ Next features, không thêm provider SDK.
2. PaaS tách web/API. Cần manifests/secrets/provider decision chưa tồn tại và tạo hai deployment control
   plane trước khi có measured need.
3. Static export. Bị loại vì auth cookie, Server Components và BFF Route Handlers cần Node.js server.

Next.js 16.3.2 local docs xác nhận Docker/Node server hỗ trợ đầy đủ, còn Docker official guide khuyến nghị
`output: "standalone"`, multi-stage build, non-root runtime và `node server.js`:

- https://nextjs.org/docs/app/getting-started/deploying
- https://docs.docker.com/guides/nextjs/#11-nextjs-with-standalone-output

## Artifact và runtime

Tạo `web/Dockerfile` ba stage dùng Node 22 bookworm-slim manifest đã kiểm tra
`sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436`:

1. `dependencies`: `npm ci` từ exact lockfile;
2. `builder`: `npm run build` với telemetry tắt;
3. `runner`: chỉ copy `.next/standalone` và `.next/static`, chạy non-root `node` user bằng
   `node server.js`, `HOSTNAME=0.0.0.0`, `PORT=3000`.

Không copy `.env`, test, local build hoặc `node_modules` từ host. `next.config.mjs` bật
`output: "standalone"`. Runtime secret/config không được bake vào image; Compose inject server-only
`DEVRADAR_API_BASE_URL=http://api:8000`.

## Compose và trust boundary

Thêm service `web`:

- phụ thuộc `api` healthy;
- bind host loopback `127.0.0.1:${DEVRADAR_WEB_HOST_PORT}:3000` để ingress provider là điểm public duy nhất;
- health check `/login` qua Node built-in `fetch`;
- `read_only`, `/tmp` và `.next/cache` tmpfs, drop toàn bộ capability, `no-new-privileges`;
- image override `DEVRADAR_WEB_IMAGE` tương tự API/crawler.

Browser chỉ nói chuyện cùng origin với web/BFF. CSP `connect-src` thu hẹp về `'self'`; localhost API
origins không còn cần trong browser policy. API vẫn enforce Origin/CORS/session/CSRF.

## Deploy, smoke và rollback

`deploy.ps1` tiếp tục giữ `-Image` là API image để compatibility và thêm `-WebImage` cùng
`-WebBaseUrl`. Build/inspect cả hai, migrate một lần, start `api` rồi `web`, sau đó chạy:

- API `/api/v1/health` smoke;
- web `/login` smoke;
- web same-origin `/api/devradar/privacy` BFF smoke để chứng minh container DNS → API data path.

`rollback.ps1` yêu cầu cả API và web image đã tồn tại, restart cả hai rồi chạy cùng smoke. Không rollback
database schema tự động. Nếu bất kỳ image/start/smoke nào fail, command exit non-zero và không in secret.

Protected/public policy yêu cầu cả API và web smoke URL là HTTPS. Local defaults vẫn dùng loopback HTTP.

## CI và supply chain

- Web quality job giữ `npm ci` + tests/lint/typecheck/build.
- Compose smoke build cả API/web, start cả hai và lưu combined logs.
- Remote rollback build/tag release + known-good cho cả hai image.
- Trivy full/advisory gate scan API, crawler và web riêng.
- Không đổi bảy required job names, nên branch protection contract không drift.

## Verification

1. TDD static contract fail trước khi web Dockerfile/service tồn tại, rồi pass.
2. `npm run check` và `docker build web` pass.
3. Compose migration → API/web health → privacy BFF smoke pass với read-only container.
4. Dual-image deploy và rollback smoke pass.
5. Default Python/static gates, Compose config và three-image Trivy gate pass.
6. Push exact SHA, chờ bảy required jobs terminal và lưu artifact evidence.

## Non-goals và boundary còn mở

- Không thêm Caddy/Nginx/Traefik hoặc expose non-loopback port; HTTPS ingress thuộc provider.
- Không chọn VPS/PaaS, registry, DNS hoặc managed secret vendor trong task này.
- Không biến web/API thành microservices; đây là hai process/artifact của cùng modular monolith.
- Không claim public deployment, external uptime hoặc off-host backup chỉ từ local/CI Compose.
