# ADR-021: Chấp nhận DigitalOcean single-host production boundary

## Status

Accepted

## Date

2026-08-23

## Context

ADR-020 đã hoàn tất API/web Compose artifact nhưng cố ý defer host, HTTPS, registry, secrets, off-host
backup và uptime provider. V6-004/V6-005/V6-007 không thể đóng bằng local/CI evidence. DevRadar là portfolio
single-operator và crawler Chromium cần giữ sandbox/capability control hiện hành.

## Decision

- Dùng một DigitalOcean Basic Droplet `4 GiB / 2 vCPU` tại `sgp1` làm initial production host.
- Giữ Docker Compose; không ánh xạ sang App Platform hoặc Kubernetes.
- Dùng một hostname, Caddy 2.10.2 pinned digest làm public TLS ingress; `/api/v1/*` tới FastAPI, path còn
  lại tới Next.js. API/web/database host ports vẫn loopback.
- Build API/crawler/web vào GHCR từ exact successful CI SHA; deploy/rollback bằng digest.
- GitHub `production` environment là managed deployment-secret source. SSH dùng pinned known-host,
  non-root deploy user và temporary runner `/32` Cloud Firewall rule được cleanup vô điều kiện.
- Dùng restic 0.19.1 pinned digest tới private DigitalOcean Spaces cho encrypted PostgreSQL backup,
  retention và restore drill.
- Dùng DigitalOcean Uptime cho external HTTPS/latency/SSL alert; GitHub Issues route tiếp tục dành cho CI.
- Thực thi theo V6-013 ingress/release, V6-014 backup/uptime và V6-015 live closeout; không nâng public
  status trước evidence provider thật.

## Alternatives considered

### DigitalOcean App Platform + Managed PostgreSQL

Rejected cho initial release vì làm lệch Compose, tách nhiều component/cost và không giữ được browser
sandbox/capability contract hiện hành một cách đã kiểm chứng.

### AWS/GCP/Kubernetes

Rejected vì thêm IAM/network/orchestration/state vượt nhu cầu portfolio single-host và chưa có measured HA
need.

### Giữ provider unspecified

Rejected vì V6 đã hết local work có thể đóng external gates; tiếp tục generic hóa chỉ tạo config giả và
không tiến gần public evidence.

## Consequences

- Single host là accepted availability risk; backup off-host và application rollback giảm recovery risk
  nhưng không tạo HA.
- Public release cần billing account, domain/DNS, scoped provider token và SSH key do operator cấp ngoài Git.
- Caddy và restic trở thành pinned operational dependencies, phải vào advisory/update review.
- GitHub-hosted deploy runner chỉ mở SSH trong bounded window; workflow cleanup failure phải tạo incident và
  operator xóa rule trước lần deploy sau.
- Chi tiết contract và verification nằm tại
  [V6-013 design](../superpowers/specs/2026-08-23-v6-013-digitalocean-production-foundation-design.md).
