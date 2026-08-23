# ADR-023: Chấp nhận boundary backup Spaces mã hóa và DigitalOcean Uptime

## Status

Accepted — khóa contract trong repository; chưa phải bằng chứng provider đã được cấu hình.

## Date

2026-08-23

## Context

V6 cần một đường khôi phục PostgreSQL độc lập với host, có retention và tín hiệu availability từ bên ngoài.
ADR-017 chỉ chấp nhận archive/restore local và bounded health probe; những capability đó không chứng minh
độ bền khi host hoặc database hỏng. Repository cũng cần giữ supply-chain gate hiện hành: image production phải
dùng digest bất biến và không chấp nhận image có HIGH/CRITICAL finding fixable.

DigitalOcean Spaces cung cấp API tương thích S3 nhưng chỉ hỗ trợ một phần feature của S3. DigitalOcean Uptime
có endpoint GET kiểm tra cấu hình check và yêu cầu scope `uptime:read` cho read-only verification. Chưa có
account, bucket, host, domain, check ID hoặc GitHub production secret trong môi trường hiện tại.

## Decision

- Dùng restic `0.19.1` từ source tarball có SHA-256 cố định trong `deploy/restic/Dockerfile`; builder Go và
  các module đã vá được pin bằng digest/version. Runtime là `FROM scratch`, non-root và chỉ chứa binary,
  CA bundle.
- Chỉ cho phép production repository dạng `s3:https://...` và restic image dạng `@sha256:<64 hex>`. Cờ
  `-AllowLocalRepository` chỉ mở test repository dạng `local:...`; cờ này không làm yếu validation của S3
  hoặc image digest.
- Password restic đi qua `RESTIC_PASSWORD_FILE` và bind mount read-only; không nhận password qua command
  argument và không ghi password/archive vào log hoặc artifact. S3 credentials chỉ được chuyển qua env file
  tạm có quyền hạn chế, rồi xóa trong cleanup.
- Workflow backup build/push image restic lên GHCR, truyền digest xuống host, login GHCR qua stdin, chạy
  encrypted backup và retention `7 daily + 4 weekly`, rồi logout và xóa file tạm. Container trên host chạy
  bằng UID/GID non-root của operator để đọc được password file `0600`, không đổi trust boundary thành root.
- Backup chỉ được coi là production evidence sau khi có Spaces bucket riêng, key policy tối thiểu, repository
  `init`, backup/list/check/restore thật, retention/prune, key rotation và RPO/RTO đo được.
- Uptime workflow chỉ verify `GET /v2/uptime/checks/{id}` với HTTPS target `/api/v1/health`; alert ID (nếu có)
  chỉ được verify bằng GET. Tạo hoặc sửa check không nằm trong workflow read-only mặc định; `Ensure` trong
  script chỉ dành cho operator có explicit `-AllowCreate` và token write scope.
- `V6-014` giữ trạng thái `In Progress` cho tới khi provider evidence thật hoàn tất. Không ghi credential,
  bucket secret, domain hoặc check ID thật vào Git.

## Alternatives considered

### Dùng official restic image floating/tag image

Rejected vì scan local của official restic `0.19.1` còn `12` HIGH/CRITICAL finding fixable và tag không tạo
được artifact bất biến cho rollback/audit.

### Ghi archive vào cùng host hoặc named volume

Rejected vì không bảo vệ trước mất host/database và không đáp ứng off-host restore requirement. Local/CI drill
tiếp tục hữu ích nhưng chỉ là prerequisite.

### Thêm object-storage SDK hoặc worker service vào ứng dụng

Rejected vì restic đã cung cấp S3-compatible backend qua process boundary; SDK/worker mới không tạo bằng chứng
durability và sẽ mở rộng dependency trước measured need.

### Dùng monitoring SaaS hoặc thêm metrics backend

Rejected cho task này. DigitalOcean Uptime là boundary provider tối thiểu; ứng dụng vẫn giữ bounded monitor
và structured events theo ADR-017 cho tới khi có nhu cầu cardinality/retention/alert-routing đo được.

## Consequences

- Có command/workflow reproducible để operator hoàn thiện Spaces/Uptime mà không sửa code hoặc đưa secret vào
  repository.
- Custom image phải được rebuild/scan khi restic, Go hoặc patched module thay đổi; GHCR package access và
  remote Docker availability trở thành prerequisite.
- S3 compatibility không đồng nghĩa mọi feature S3 đều có; workflow chỉ dùng operations đã kiểm thử với restic
  (`backup`, `check`, `forget --prune`) và runbook phải ghi rõ giới hạn.
- Khi chưa có provider evidence, V6-005/V6-007 và public release vẫn mở; local restic smoke không được gọi là
  encrypted off-host backup hoặc measured RPO/RTO.

## Official references

- Restic password file/S3 repository: https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html
- Restic Docker/source build: https://github.com/restic/restic/blob/master/docker/Dockerfile
- DigitalOcean Spaces S3 compatibility: https://docs.digitalocean.com/products/spaces/reference/s3-compatibility/
- DigitalOcean Uptime API and `uptime:read`: https://docs.digitalocean.com/products/uptime/reference/api/
- Go module verification: https://go.dev/ref/mod
