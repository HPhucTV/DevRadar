# V6-013 — DigitalOcean production foundation design

**Trạng thái:** Accepted
**Ngày:** 2026-08-23

## Mục tiêu

Đưa topology Compose đã kiểm chứng của DevRadar tới một public single-host deployment có HTTPS,
artifact theo digest, managed deployment secrets, encrypted off-host PostgreSQL backup và external
uptime evidence. Thiết kế giữ modular monolith cùng single-operator boundary; không biến V6 thành bài toán
HA, Kubernetes hoặc multi-region.

Thiết kế được triển khai theo ba lát cắt tuần tự:

1. `V6-013`: ingress, registry/release manifest và production deployment contract;
2. `V6-014`: encrypted Spaces backup, retention/restore và DigitalOcean Uptime;
3. `V6-015`: live host/domain deployment, rotation/revocation drill và V6 closeout audit.

Mỗi lát cắt chỉ được `Done` bằng evidence đúng boundary. Static/local contract không thay thế live provider
run, public TLS smoke hoặc off-host restore.

## Lựa chọn provider

### DigitalOcean SGP1 Droplet + Compose — chọn

Khởi đầu bằng một Basic Droplet `4 GiB / 2 vCPU` tại `sgp1`. Đây là mức nhỏ nhất có headroom hợp lý cho
PostgreSQL, FastAPI + local MiniLM, Next.js và một crawler Chromium bounded trên cùng host. API, web,
crawler và database tiếp tục dùng image/Compose contract hiện tại; provider chỉ bổ sung host, firewall,
DNS, ingress, registry access, secret delivery, object storage và uptime.

### DigitalOcean App Platform + Managed PostgreSQL — không chọn

App Platform cung cấp TLS/secrets tốt nhưng buộc ánh xạ API, web và crawler thành component riêng. Browser
sandbox/capability contract hiện tại không được giữ nguyên, database chi phí riêng và deploy/rollback không
còn chạy qua Compose đã kiểm chứng.

### Cloud VM nhiều provider hoặc Kubernetes — không chọn

AWS/GCP/Kubernetes có thể đáp ứng mọi boundary nhưng thêm IAM, network, state và orchestration không có
measured need. Với portfolio single-operator, chi phí vận hành và số control plane lớn hơn lợi ích.

## Topology public

Một hostname do operator sở hữu trỏ `A`/`AAAA` tới Droplet. Caddy là public ingress duy nhất:

- với hostname ví dụ `devradar.example.com`, `https://devradar.example.com/api/v1/*` reverse proxy nguyên
  URI tới `api:8000`;
- mọi path còn lại reverse proxy tới `web:3000`;
- Caddy tự quản lý certificate và HTTP → HTTPS redirect;
- host chỉ mở `80/tcp`, `443/tcp`; API, web và PostgreSQL vẫn bind loopback như Compose hiện hành;
- Caddy data/config dùng named volume; config được mount read-only.

Ingress dùng custom patched Caddy `v2.11.4` theo [ADR-022](../../decisions/0022-accept-patched-caddy-scratch-ingress.md).
Official Caddy 2.10.2/2.11.4 và Traefik 3.7.10 không qua zero-fixable gate, nên runtime build từ pinned Go
builder, khóa ba patched transitive modules rồi chạy `FROM scratch` non-root trên high ports. `Caddyfile`
không nhận upstream hoặc directive từ secret/user input; chỉ hostname bounded được inject qua environment.

## Artifact và release

GitHub Actions build bốn image `api`, `crawler`, `web`, `ingress` từ một exact commit đã có successful
`DevRadar CI` run. Image được push vào GHCR, gắn immutable commit tag và deploy bằng registry digest;
floating tag không được dùng làm release/rollback identity. PostgreSQL/pgvector cũng dùng manifest digest
từ managed production config. Release manifest chỉ chứa commit, build/run ID và artifact digests, không
chứa credential.

Workflow production là `workflow_dispatch`, dùng `environment: production`, `concurrency` một deployment và
fail closed nếu:

- release SHA không phải 40 lowercase hex hoặc không thuộc `main`;
- exact SHA chưa có terminal successful `DevRadar CI` run;
- host/domain/firewall/known-host hoặc secret bắt buộc thiếu;
- image không pull/inspect được bằng digest;
- migration, API/web health, HTTPS smoke hoặc rollback smoke fail.

Deploy giữ forward-only migration theo ADR-016. Rollback chỉ đổi API/web image về known-good digest và không
tự downgrade schema.

## Secrets và SSH boundary

GitHub `production` environment là managed source cho deployment secrets. Workflow chỉ nhận secret sau
environment gate, không in/transcode secret ra artifact. Runtime env được chuyển qua SSH với mode `0600`,
đặt ngoài repository và ghi `DEVRADAR_SECRET_SOURCE=managed`.

SSH phải dùng pinned `known_hosts`, `BatchMode=yes`, dedicated non-root deploy user và key riêng. DigitalOcean
Cloud Firewall mặc định không cho Internet-wide SSH. Workflow dùng scoped token `firewall:read` +
`firewall:update` để thêm đúng runner IPv4 `/32` trong thời gian deploy và xóa rule trong unconditional
cleanup. `80/443` vẫn public; database không có public firewall rule. Deploy concurrency ngăn hai run cùng
quản lý một temporary SSH rule.

Credential không được paste vào chat, command line, issue, artifact hoặc Git. Rotation drill tạo key/token
mới, deploy + smoke bằng credential mới rồi revoke credential cũ; evidence chỉ ghi identity/timestamp/status.

## Off-host backup và monitoring

PostgreSQL custom dump tiếp tục được tạo bằng tool/version trong database container. `V6-014` đưa dump tới
private DigitalOcean Spaces repository bằng official restic image
`ghcr.io/restic/restic:0.19.1@sha256:2f0373803493361f9304a57150d464677f69a9dad487afec202105aafb2592f2`.
Restic cung cấp client-side encryption, repository keys, S3-compatible backend và retention; không thêm SDK
vào application dependency.

- schedule ban đầu: daily;
- policy: giữ 7 daily + 4 weekly snapshots, rồi `forget --prune`;
- RPO target: 24 giờ;
- RTO target: 2 giờ cho isolated restore + validation trên dataset portfolio hiện tại;
- local plaintext dump nằm trong private temp directory và luôn xóa bằng trap sau upload/failure;
- restore drill tải snapshot về isolated path/database, kiểm `alembic_version` cùng row invariants rồi xóa.

Mất restic repository password đồng nghĩa mất khả năng restore. Rotation phải dùng `restic key add`, verify
key mới, rồi mới `key remove` key cũ. Spaces key chỉ có quyền trên backup bucket và được rotate riêng.

DigitalOcean Uptime tạo một HTTPS check cho public health endpoint cùng latency/SSL alerts. GitHub incident
workflow tiếp tục quan sát CI; Uptime quan sát runtime. Không thêm Prometheus/OpenTelemetry khi chưa có
measured need.

## Verification và exit gates

### V6-013

1. Contract test RED trước khi production Compose/Caddy/workflow tồn tại, GREEN sau implementation.
2. `docker compose -f compose.yaml -f compose.production.yaml config --quiet` pass với sanitized fixture.
3. Caddy config validate và local HTTP routing smoke tới real API/web containers pass; không claim public TLS.
4. Workflow contract khóa exact-SHA CI check, environment gate, năm digest images, pinned known-host và
   firewall cleanup.
5. Full repository gates và remote seven-check CI pass trên exact implementation SHA.

### V6-014

1. Restic image/digest, S3 repository, password/key và retention contract pass với sanitized fixture.
2. Local disposable S3-compatible integration hoặc real Spaces bounded drill chứng minh backup/list/restore;
   chỉ real Spaces evidence mới đóng off-host gate.
3. System schedule, failure exit và metadata-only evidence được kiểm chứng.
4. DigitalOcean Uptime check/alert được GET lại từ provider API.

### V6-015

1. Public DNS, certificate, HTTPS API/web/privacy/auth smokes pass từ ngoài Droplet.
2. Release và known-good rollback chạy bằng exact image digests.
3. Managed secret rotation/revocation và temporary SSH firewall cleanup pass.
4. Off-host restore ghi backup/restore timestamps, measured RPO/RTO và validation không chứa PII.
5. Public privacy/source policy visible; V6-004/V6-005/V6-007 chỉ chuyển `Done` sau audit evidence đầy đủ.

## Non-goals

- HA database, multi-Droplet failover, load balancer hoặc zero-downtime schema migration;
- Kubernetes, Terraform state, Redis, distributed worker hoặc external vector database;
- public full-JD syndication hay mở rộng crawler permission;
- tự mua domain, tự tạo billing account hoặc ghi provider credential vào repository.

## Nguồn chính thức

- DigitalOcean region matrix: https://docs.digitalocean.com/platform/regional-availability/
- DigitalOcean Droplet pricing: https://www.digitalocean.com/pricing/droplets
- DigitalOcean firewall rules/API: https://docs.digitalocean.com/products/networking/firewalls/how-to/configure-rules/
- DigitalOcean Spaces pricing/S3 support:
  https://docs.digitalocean.com/products/spaces/details/pricing/ và
  https://docs.digitalocean.com/products/spaces/reference/s3-compatibility/
- DigitalOcean Uptime: https://docs.digitalocean.com/products/uptime/
- Caddy automatic HTTPS/reverse proxy:
  https://caddyserver.com/docs/quick-starts/https và
  https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
- GitHub environments/secrets/GHCR digest:
  https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments và
  https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- Restic repository/encryption/official image:
  https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html,
  https://restic.readthedocs.io/en/stable/070_encryption.html và
  https://github.com/restic/restic/blob/master/doc/020_installation.rst
