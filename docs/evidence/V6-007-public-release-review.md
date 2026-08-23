# V6-007 — Public release review

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — local/protected evidence đã có; public deployment boundary chưa được cấp.

## Evidence đã kiểm chứng trong repository

| Boundary | Evidence hiện tại | Kết luận |
|---|---|---|
| Auth/session/CSRF/authorization | Default và PostgreSQL integration suites; V6-002 evidence | Local/protected runtime có test; chưa phải public endpoint evidence |
| API/web hardening | [V6-003 evidence](V6-003-hardening.md) | Done; rate limit, headers, CORS, secret guard và Trivy gate pass |
| Deploy/migration/rollback | [V6-004 evidence](V6-004-ci-deploy.md) | Local fresh DB deploy và application-image rollback pass; không tự downgrade |
| Remote CI/rollback/artifact | [V6-004 evidence](V6-004-ci-deploy.md) | Run #21 trên SHA `ebc12f2` pass cả bảy jobs; PostgreSQL, Compose, rollback và backup metadata artifacts retention 14 ngày |
| Protected `main` | [V6-004 evidence](V6-004-ci-deploy.md) | Strict seven-check branch protection, linear history và conversation resolution bật; force-push/deletion tắt; admin bypass được giữ cho single owner |
| Backup/restore/monitor | [V6-005 evidence](V6-005-backup-monitoring.md) | Local archive 610,431,168 bytes restore pass; remote CI runs #20/#21 lặp lại backup/restore drill và metadata artifact không chứa dump |
| Queue decision | [V6-006 evidence](V6-006-queue-pressure.md) và [ADR-018](../decisions/0018-do-not-add-redis-worker-pool-after-v6-benchmark.md) | Giữ PostgreSQL queue/one-shot worker |
| Container advisory | [ADR-019](../decisions/0019-accept-pinned-trivy-container-gate.md) | API/crawler scan có 0 fixable HIGH/CRITICAL; unfixed residual risk được theo dõi |

## Gate chưa thể đóng

- Chưa có HTTPS ingress/hostname thật và post-deploy smoke từ bên ngoài loopback.
- Chưa có managed secret provider, rotation/revocation drill và operator access audit.
- Chưa có off-host encrypted PostgreSQL backup schedule, retention, RPO/RTO và restore timestamp/operator
  evidence; local archive không chứng minh durability production.
- Chưa có alert routing/incident contact thật hoặc privacy/terms notice đã publish cho public traffic.

## External-state audit ngày 2026-08-23

- `.env.local` chỉ có tên biến `DEVRADAR_DEEPSEEK_API_KEY`; không ghi hoặc expose giá trị secret.
- Không có provider CLI hoặc credential environment cho VPS/cloud/managed database/object storage/HTTPS.
- GitHub metadata public kiểm tra được `environments.total_count=0` và `deployments=[]`. Authenticated
  branch-protection GET xác nhận `main` đã có strict seven-check policy; credential không được ghi vào
  output, file hoặc Git.
- Vì không có hostname/ingress thật, chưa thể chạy `scripts/deploy.ps1 -RequireHttps` hoặc rollback drill
  từ bên ngoài loopback mà không bịa target.

## Release decision

Giữ V6-007 ở `In Progress`. Source đã được push để kích hoạt remote CI, nhưng chưa tuyên bố public release
cho tới khi các boundary provider/operator còn lại có evidence. Không thêm Redis, reverse proxy, cloud SDK
hoặc secret vào repository chỉ để lấp khoảng trống evidence; deployment provider phải cung cấp chúng và được
kiểm thử theo runbook.
