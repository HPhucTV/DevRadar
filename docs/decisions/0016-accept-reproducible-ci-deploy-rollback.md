# ADR-016: Reproducible CI và forward-compatible deploy/rollback

## Status

Accepted

## Date

2026-08-23

## Context

V6 cần đưa artifact đã kiểm thử qua migration, deploy và smoke một cách lặp lại được, đồng thời
khôi phục nhanh khi application image có lỗi. Repository đã có dependency lock, Docker Compose,
Alembic và health endpoint nhưng chưa có pipeline hoặc command surface dùng chung cho local/CI.

Migration schema có thể chứa thay đổi không tương thích ngược; rollback database tùy tiện sau khi đã
deploy application mới có thể gây mất dữ liệu hoặc làm image cũ không khởi động. Vì vậy rollback cần
được định nghĩa ở application artifact boundary, còn schema thay đổi phải đi theo expand/contract và
forward migration.

## Decision

- GitHub Actions là enforcement layer cho Python lint/format/type/test, PostgreSQL integration, web
  check/audit, Compose migration/API smoke và container advisory scan.
- Dependency runtime/test tiếp tục cài từ lock có hash; workflow không cài package không có trong lock.
- Docker image được build trước migration, Compose nhận image qua `DEVRADAR_APP_IMAGE`, và deploy chỉ
  tiếp tục sau khi database healthy, `alembic upgrade head` thành công và `/api/v1/health` trả `status=ok`.
- `scripts/deploy.ps1` là command surface cho local/protected deployment; production/public class
  fail-closed nếu thiếu HTTPS, auth, Secure cookie, managed secret, explicit HTTPS CORS, operator hash
  hoặc non-default database password.
- `scripts/rollback.ps1` chỉ đổi về application image đã tồn tại và chạy lại health smoke. Không tự động
  chạy `alembic downgrade`; migration rollback phải dùng forward-compatible fix hoặc runbook được review.
- `scripts/smoke.ps1` chỉ kiểm tra health contract; nó không được dùng thay cho database, auth, crawl,
  restore hoặc browser evidence.
- CI container advisory scan dùng Docker Scout critical/high gate và fail rõ ràng khi repository secret
  chưa được cấu hình; không suy diễn an toàn từ image build thành công.

## Alternatives considered

### Tạo một reverse proxy/TLS service mới trong Compose

Rejected ở V6-004 vì thêm runtime và certificate lifecycle chưa cần cho local/protected deploy. HTTPS
public được terminate ở ingress/deployment provider; application vẫn fail-closed khi public class không
đủ cấu hình.

### Cho phép `alembic downgrade` tự động khi rollback

Rejected vì migration downgrade có thể phá dữ liệu đã ghi bởi image mới. Expand/contract và application
rollback độc lập có blast radius nhỏ hơn.

### Bỏ qua container scan khi Docker Scout chưa login

Rejected vì làm mất bằng chứng advisory scan; gate phải `Blocked` thay vì false-green.

## Consequences

- Local deploy/rollback có command reproducible và không cần secret thật với `.env.example`.
- Public deploy vẫn cần configured managed secret store, HTTPS ingress, Trivy advisory DB access và
  operator-run restore/deploy evidence.
- Mọi migration mới phải được review theo backward-compatibility contract; rollback image không hoàn tác
  schema tự động.
- GitHub Actions workflow có thêm official action references và cần Dependabot cập nhật định kỳ.

## Amendment

Lựa chọn Docker Scout cho container advisory scan trong decision ban đầu được thay thế bởi
[ADR-019](0019-accept-pinned-trivy-container-gate.md). Các quyết định còn lại về CI, migration và
application-image rollback vẫn giữ nguyên hiệu lực.
