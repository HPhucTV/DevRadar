# ADR-022: Chấp nhận patched Caddy scratch ingress

## Status

Accepted — supersede phần Caddy artifact trong ADR-021; các quyết định DigitalOcean single-host khác vẫn
có hiệu lực.

## Date

2026-08-23

## Context

ADR-021 chọn Caddy Official Image `2.10.2` làm ingress. Khi đưa image này vào Trivy gate đã Accepted ở
ADR-019, scanner digest hiện hành phát hiện `78` HIGH/CRITICAL findings có bản sửa. Nâng lên Caddy Official
Image `2.11.4` vẫn còn `19` findings fixable. Traefik Official Image `3.7.10` được kiểm như phương án thay
thế và còn `10` findings fixable trong tổng số `11` HIGH/CRITICAL.

Public ingress là trust boundary trực tiếp nhận Internet traffic. Nới hoặc bypass zero-fixable gate chỉ để
dùng official runtime image sẽ mâu thuẫn với V6 supply-chain policy. DevRadar không cần plugin Caddy ngoài
standard modules.

## Decision

- Build Caddy `v2.11.4` như dependency từ entrypoint chuẩn của cùng release, trên
  `golang:1.26.6-alpine3.23` với manifest digest pinned.
- Override đúng các transitive modules có advisory đã có bản sửa:
  `golang.org/x/net@v0.56.0`, `golang.org/x/text@v0.39.0` và
  `google.golang.org/grpc@v1.82.1`.
- `go mod tidy`, `go mod verify`, exact-version assertions và `caddy version` module hash là build gates;
  build fail nếu graph không chọn đúng ba version hoặc binary không báo `v2.11.4`.
- Runtime dùng `FROM scratch`, CA certificates, embedded timezone data, `USER 10001:10001`, high ports
  `8080/8443`, read-only root, `cap_drop: ALL` và không cấp `NET_BIND_SERVICE`.
- Cả full HIGH/CRITICAL report và `--ignore-unfixed --exit-code 1` gate của pinned Trivy phải chạy trên
  ingress image cùng API/crawler/web images.
- Workflow production build/push ingress từ exact successful CI SHA và deploy bằng GHCR digest. Database
  pgvector cũng phải được chọn qua `DEVRADAR_DATABASE_IMAGE` có immutable digest.

## Alternatives considered

### Giữ Caddy Official Image 2.10.2 hoặc 2.11.4

Rejected vì lần lượt còn `78` và `19` HIGH/CRITICAL findings fixable trong artifact chạy production.

### Đổi sang Traefik Official Image 3.7.10

Rejected vì vẫn còn `10` findings fixable, đồng thời thêm một ingress contract mới mà không giải quyết
security gate.

### Bỏ qua hoặc suppress findings

Rejected vì findings có bản sửa và ingress là public trust boundary. Reachability/suppression không thay
thế patched artifact trong trường hợp này.

## Consequences

- Runtime image nhỏ, không có shell/package manager và đã đạt `0` HIGH/CRITICAL với scanner database tại
  thời điểm verification.
- Build ingress tải Go module graph nên chậm hơn dùng prebuilt image; CI cache có thể được cân nhắc chỉ khi
  measured duration trở thành bottleneck.
- Caddy release, Go builder digest và ba override phải được review cùng nhau khi Dependabot/advisory gate
  yêu cầu nâng version; không tự nâng một module rồi suy diễn compatibility.
- ADR-021 vẫn quyết định provider, topology, firewall, backup và uptime. Chỉ dòng chọn official Caddy
  artifact bị supersede.

## Official references

- Caddy build from source: https://caddyserver.com/docs/build
- Caddy `v2.11.4` entrypoint:
  https://github.com/caddyserver/caddy/blob/v2.11.4/cmd/caddy/main.go
- Go module checksum và tidy behavior: https://go.dev/ref/mod

