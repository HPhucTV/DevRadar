# Runbook: Deploy và rollback

## Deploy

`scripts/deploy.ps1` thực hiện Compose config, API/web image build/inspect, database wait,
`alembic upgrade head`, API/web wait và health/BFF smoke. Protected/public target phải dùng HTTPS cho cả
hai smoke URL, authentication, Secure cookie, managed secret source, HTTPS CORS và non-default database
password.

```powershell
.\scripts\deploy.ps1 -EnvironmentFile .env.local -ProjectName devradar -Image registry.example/devradar-api:<digest> -WebImage registry.example/devradar-web:<digest> -BaseUrl https://api.devradar.example -WebBaseUrl https://devradar.example -RequireHttps
```

Không đặt registry credential trong command history; dùng provider secret/identity.

## DigitalOcean production workflow

V6-013 chỉ cho phép chạy workflow thủ công sau khi đã có DigitalOcean host/domain và GitHub `production`
environment. Operator cấu hình variables `DEVRADAR_DOMAIN`, `DEVRADAR_HOST`, `DEVRADAR_SSH_USER`,
`DEVRADAR_FIREWALL_ID`; secrets gồm production env base64, SSH private key, pinned known-hosts và scoped
`DIGITALOCEAN_TOKEN`. Không đưa các giá trị này vào Git, chat hoặc log.

`release_sha` phải là 40 ký tự lowercase hex, là ancestor của `main` và có run `DevRadar CI` terminal
success đúng SHA. Workflow build/push API, crawler, web và patched Caddy ingress; production env đồng thời
phải chứa `DEVRADAR_DATABASE_IMAGE` là pgvector digest. Remote Compose pull tất cả năm digest trước khi
migrate và start.

SSH Cloud Firewall chỉ mở đúng runner IPv4 `/32`. Cleanup intent được ghi trước request Add; step `if:
always()` xóa rule, logout GHCR và xóa temp files kể cả deploy hoặc smoke fail. Nếu cleanup fail, không chạy
lần deploy kế tiếp trước khi operator kiểm tra/xóa rule thủ công.

V6-013 evidence hiện chỉ có local contract/image/Compose smoke; chưa được gọi là public deploy cho tới khi
remote exact-SHA CI pass và V6-015 ghi được provider/DNS/TLS/rotation evidence.

## Rollback

1. Xác định API và web image digests cuối cùng đã pass smoke và không có unresolved critical/high advisory.
2. Kiểm tra migration compatibility; không downgrade database tự động.
3. Chạy:

   ```powershell
   .\scripts\rollback.ps1 -EnvironmentFile .env.local -ProjectName devradar -Image registry.example/devradar-api:<known-good-digest> -WebImage registry.example/devradar-web:<known-good-digest> -BaseUrl https://api.devradar.example -WebBaseUrl https://devradar.example -RequireHttps
   ```

4. Kiểm tra health, login/session, owner scope, read API, alert disabled/allow-list và error rate.
5. Nếu rollback smoke fail, giữ traffic ở maintenance/previous known-good target và mở incident; không
   lặp deploy mù.
