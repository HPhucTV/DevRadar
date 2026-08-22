# V5-005 — CV matching UI và deletion

## Trạng thái

`complete` trong phạm vi local/protected V5. UI thực hiện upload CV → tạo
`ResumeProfile` → generate/replay `JobMatch` → đọc bounded evidence → xóa profile
và matches. Authentication public, rate limiting và anonymous CV exposure vẫn là V6.

## Thiết kế và boundary

- `/cv-match` là Server Component shell với một Client Component island cho state,
  file picker và event handlers theo Next.js 16 App Router.
- Next Route Handler dưới `/api/devradar/resume-profiles` là same-origin BFF proxy
  tới FastAPI `/api/v1`; browser không cần CORS và không nhận backend URL trực tiếp.
- `X-DevRadar-Owner` chỉ tồn tại trong React memory và request header; không có
  `localStorage`, cookie, analytics hoặc log token.
- FormData chỉ nhận PDF/DOCX, kiểm tra 5 MiB ở client/BFF và để backend V5-003
  thực hiện parser/signature/stream/decompression limits authoritative.
- Delete giữ `204 No Content` qua proxy, xóa local state và profile visibility trở
  thành `404`; derived `JobMatch` cascade theo PostgreSQL.
- Không render raw CV text, file bytes, owner hash, vector, extraction payload hoặc
  arbitrary job URL.

## Verification

```text
npm test --prefix web              4 passed
npm run lint --prefix web          pass
npm run typecheck --prefix web     pass
npm run build --prefix web         pass; API proxy routes listed in build output
npm audit --prefix web --audit-level=high   0 vulnerabilities
```

Browser smoke dùng Playwright với API/PostgreSQL thật và DOCX synthetic trong thư
mục tạm:

```text
/cv-match render                  pass
owner/file validation             pass
upload through same-origin BFF    200
local generation                  200; scoringVersion=job-match-scoring-v2
generation counts                 considered=3339, available=3339, stored=100
match list                        100 current rows with bounded job/evidence fields
delete profile                    204
post-delete UI/state              pass; profile/matches removed from page
```

The original file and synthetic content are not committed or retained as evidence.
API was recreated with `DEVRADAR_CV_LOCAL_ENABLED=false` after the smoke and health
returned `{"data":{"status":"ok"}}`.

## Non-goals and next step

V5-005 does not add authentication, persistent browser sessions, public CV sharing,
alert delivery or browser automation for arbitrary sources. V5-006 subsequently
delivered one idempotent alert connector; V5-007 closes the protected V5 demo
surface.
