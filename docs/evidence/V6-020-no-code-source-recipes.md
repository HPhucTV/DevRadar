# V6-020 — No-code Source Recipes

**Status:** `In Progress`

**Boundary:** single-operator `LOCALHOST_SERVICE`; không phải public deployment evidence

**Decision:** [ADR-026](../decisions/0026-accept-owner-overridden-source-recipes.md)

## Scope

V6-020 thay static/source-specific adapter và V6-016 Custom Source runtime bằng một generic
`SourceRecipe`:

- listing URL + seniority filter, fixed schedule và bounded budgets;
- versioned `terms_notice` với owner acknowledgement; acknowledgement không phải permission/legal
  certification;
- structured data/HTTP-first preview, isolated Playwright fallback và visual mapping bằng opaque IDs;
- generic pagination/detail ingestion, PostgreSQL queue/provenance và false-removal protection;
- localhost-only API/BFF/dashboard cùng one-click Windows launcher.

Technical barriers không override được: CAPTCHA, authentication, paywall, anti-bot, access denial, SSRF
và redirect escape chuyển recipe sang `blocked`, không retry/bypass.

## Destructive migration

Revision `b4c6d8e0f2a1` purge source-derived graph và thêm Source Recipe schema trong một transaction; không
backup và không khôi phục dữ liệu purge khi downgrade. Revision `c5d7e9f1a3b2` chỉ drop bảng
`custom_source_profiles` sau khi assert bảng rỗng; downgrade chỉ tạo schema rỗng.

## Evidence đã có trước closeout

- PostgreSQL focused hard-cut/migration gate: `16 passed`.
- Full Python/PostgreSQL regression sau hard cut: `379 passed`.
- Web gate sau hard cut: `61` tests, ESLint, TypeScript và Next.js production build pass.
- Ruff lint/format và mypy pass sau hard cut.
- Runtime scan không còn old adapter/custom-source CLI/API/BFF implementation; historical ADR/evidence
  vẫn được giữ nguyên để truy vết.
- `start-devradar.cmd` chạy bằng Windows PowerShell, build/migrate/start đủ API/web/crawler, API + web
  smoke pass và chỉ sau đó mở dashboard. Web smoke dùng `-UseBasicParsing` để tương thích PowerShell 5.1.
- Launcher/docs contract `13 passed`; web hiện có `62` tests cùng ESLint, TypeScript và production build
  pass; Compose crawler profile config pass.
- Poster `/sources` là browser capture thật `1600×900`, `175302` bytes; desktop/mobile không horizontal
  overflow và không có console warning/error. Database capture có `0` recipe, không chứa PII/secret.

## Gate còn mở

- desktop + 320px browser workflow và negative barrier/false-removal cases;
- bounded live preview matrix cho mười catalog hints;
- secrets/supply-chain/container scans;
- review, merge, push và required GitHub Actions trên exact merged SHA.

Không đổi trạng thái V6-004, V6-005, V6-007 hoặc V6-014: public HTTPS, managed secrets, provider backup,
RPO/RTO và public uptime evidence vẫn chưa được task này cung cấp.
