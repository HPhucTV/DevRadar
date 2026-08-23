# V6-013 — DigitalOcean production foundation

**Ngày ghi nhận:** 2026-08-23  
**Trạng thái:** `Done` cho V6-013 — local artifact/workflow contract và remote exact-SHA CI đã pass;
live DigitalOcean deploy vẫn chưa có evidence và không được claim.

## Đã triển khai

- `compose.production.yaml` thêm một public ingress route cố định: `/api/v1/*` tới FastAPI, path còn lại
  tới Next.js; API/web/database host ports vẫn dùng contract loopback hiện hành.
- `deploy/caddy/` build Caddy `v2.11.4` từ pinned Go builder và standard entrypoint, override
  `x/net v0.56.0`, `x/text v0.39.0`, `grpc v1.82.1`, rồi chạy scratch runtime non-root trên
  `8080/8443`.
- Production config require đúng một assignment cho domain/class/auth/secret/database/image values,
  single-quoted PBKDF2 operator hash và immutable digest cho database/API/crawler/web/ingress.
- DigitalOcean firewall helper chỉ nhận canonical UUID + IPv4, tạo/xóa đúng một SSH `/32` rule và không
  lộ bearer token khi provider trả lỗi.
- Manual `production` workflow xác minh exact lowercase SHA thuộc `main` và có successful `DevRadar CI`,
  build/push bốn GHCR artifacts, resolve digests, validate managed env, pin known-host, mở/cleanup SSH
  firewall rule, deploy Compose và chạy external HTTPS smokes.
- Workflow chỉ cấp `DIGITALOCEAN_TOKEN` cho hai step firewall; cleanup intent được ghi trước mutation và
  mọi temp credential bị xóa ở `if: always()`.
- Production database dùng
  `pgvector/pgvector@sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a`,
  không dùng floating tag trong managed environment.

## Artifact và advisory evidence

Pinned Trivy:
`aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969`.

| Candidate | HIGH/CRITICAL | Fixable | Disposition |
|---|---:|---:|---|
| Caddy Official 2.10.2 | 78 | 78 | Rejected |
| Caddy Official 2.11.4 | 19 | 19 | Rejected |
| Traefik Official 3.7.10 | 11 | 10 | Rejected |
| DevRadar patched Caddy 2.11.4 scratch | 0 | 0 | Accepted bởi ADR-022 |

Final local ingress image:

```text
image id: sha256:b21d5faf4acfb1c9c2519c274e0480eea8b60206d3d63eec04cd2de35600a7f0
runtime size: 17,444,110 bytes
platform: linux/amd64
user: 10001:10001
caddy version: v2.11.4 h1:XKxkMTgNSizEvKG6QHue6cAsFOteU2qA61w2tKkCWi0=
Trivy full HIGH/CRITICAL report: 0
Trivy fixable gate: 0, exit 0
```

Build log đã assert đúng ba patched module versions, `go mod verify` pass và fail-closed nếu Caddy version
không khớp release. [ADR-022](../decisions/0022-accept-patched-caddy-scratch-ingress.md) ghi rationale và
supersede đúng phần artifact của ADR-021.

## Contract và local smoke

- Production contract: `12 passed`; gồm missing/duplicate config, unquoted/malformed PBKDF2, thiếu ingress
  digest, injected firewall IP, mock POST/DELETE payload, no-token-leak và secret scanner regression.
- Workflow-sensitive regression: production + web deployment + CI incident tests đã pass.
- `actionlint v1.7.12` trên `.github/workflows/deploy-production.yml`: exit `0`.
- Caddy config validate từ final image: `Valid configuration`.
- Pinned Trivy full report và fixable gate trên final ingress: đều exit `0`.
- Real two-file Compose project dùng port cô lập API `38000`, web `33000`, database `35432`, ingress HTTP
  `18080`, HTTPS `18443`; migration lên Alembic head và ba route sau pass:
  `/api/v1/health`, `/login`, `/api/devradar/privacy` (`privacy-v1`).
- Ingress inspect: `ReadonlyRootfs=true`, `CapDrop=["ALL"]`, không `CapAdd`,
  `no-new-privileges:true`; chỉ `/data` và `/config` writable, `Caddyfile` bind read-only.
- Teardown dùng `down` không `--volumes`; named volumes được giữ.

## Remote exact-SHA evidence

[DevRadar CI run #32623904568](https://github.com/HPhucTV/DevRadar/actions/runs/32623904568) trên exact SHA
`47f2b6b8c4b1222ce5b7bc74ae9e10f26691429c` hoàn tất `success` ngày 2026-08-23. Cả bảy required jobs đều
terminal `success`:

- Python quality/default tests;
- PostgreSQL integration tests;
- web tests/lint/typecheck/build;
- Compose migration/API/ingress smoke;
- remote application rollback;
- remote PostgreSQL backup/restore drill;
- full và fixable Trivy critical/high gate cho API/crawler/web/ingress.

Artifact metadata của run, tất cả chưa expired và retention tới 2026-09-06:

| Artifact | Size | Digest |
|---|---:|---|
| `compose-smoke-32623904568` | 3,137 bytes | `sha256:4ff365f5b59a9b48b023e988d654d696d2ba975a249f3afa886c6de83767ee36` |
| `remote-rollback-32623904568` | 2,569 bytes | `sha256:f20e59cc659ed002c5663cde89776cb98ee8c60b0b013274f2abbb21a0cee555` |
| `remote-backup-32623904568` | 1,758 bytes | `sha256:a3345fac3d395a5af9d5d84f8170729aeeba5b90a1a31cb9652d61f7169584a4` |
| `postgresql-tests-32623904568` | 2,171 bytes | `sha256:a0e6a1d803d7539b449a8c4fb7695d468baf186a6524312835dd7382861b4374` |

The production `workflow_dispatch` was not invoked, so the run did not push to GHCR, mutate a DigitalOcean
firewall, or deploy a host. No incident issue was created on the successful CI path.

## Boundary còn mở

- Chưa có DigitalOcean account/Droplet/firewall/domain/GitHub production environment; workflow chưa mutate
  provider hoặc deploy public host.
- Chưa có public DNS, certificate, external HTTPS/auth/privacy smoke hoặc managed-secret rotation evidence.
- Off-host restic/Spaces, measured RPO/RTO và DigitalOcean Uptime thuộc V6-014/V6-015.
- Vì vậy V6-004/V6-005/V6-007 vẫn `In Progress`; local smoke không được dùng để claim public release.
