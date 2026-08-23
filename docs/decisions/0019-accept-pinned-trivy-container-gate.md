# ADR-019: Pinned Trivy container advisory gate

## Status

Accepted

## Date

2026-08-23

## Context

V6-003 cần advisory scan cho cả API image và crawler image. Docker Scout được ghi trong ADR-016,
nhưng local gate bị chặn bởi yêu cầu Docker account/login; không được biến blocker quyền truy cập
thành false-green hoặc buộc repository phụ thuộc credential ngoài phạm vi.

## Decision

- Dùng image Trivy chính thức `aquasec/trivy` với digest cố định
  `sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969`.
- Scan qua Docker socket cho hai trust boundary riêng: `devradar-app` (API, không browser) và
  `devradar-crawler` (Playwright browser).
- Mỗi image phải tạo full HIGH/CRITICAL report gồm cả fixed và unfixed findings. Gate chỉ pass khi
  không còn finding có `FixedVersion`; finding chưa có bản sửa được ghi riêng trong output/evidence,
  không bị che bởi `--ignore-unfixed`.
- CI và local script dùng cùng scanner digest, severity và exit-code semantics. Scanner không được
  coi image build thành bằng chứng an toàn; nếu scanner/image/socket không chạy thì gate fail.

## Alternatives considered

### Docker Scout với repository credentials

Giữ trong ADR-016 cho lịch sử, nhưng bị defer vì phụ thuộc Docker account/login không có sẵn trong
local evidence và không cần thiết khi scanner chính thức có thể chạy qua Docker socket.

### Chỉ chạy `--ignore-unfixed`

Rejected vì sẽ che mất fixed vulnerability. Full report vẫn phải được thu thập và đếm riêng trước khi
đánh giá gate.

### Scan API image nhưng bỏ qua crawler image

Rejected vì crawler có browser/OS dependency và là trust boundary khác; cần scan độc lập dù build nặng hơn.

## Consequences

- V6-003 có gate reproducible không cần Docker Scout credential; scanner supply-chain vẫn cần network để
  tải advisory DB trong môi trường sạch.
- API image lean hơn vì không chứa browser; crawler image chịu scan riêng và chỉ bật qua Compose profile.
- Unfixed upstream advisories vẫn là residual risk cần theo dõi, không được báo cáo như zero vulnerabilities.
- ADR-016 tiếp tục áp dụng cho CI/deploy/rollback; riêng lựa chọn container advisory scanner được thay thế
  bởi ADR này.

## Sources

- [Trivy image CLI](https://trivy.dev/docs/latest/references/configuration/cli/trivy_image/)
- [Official Trivy GitHub Action examples](https://github.com/aquasecurity/trivy-action#usage)
