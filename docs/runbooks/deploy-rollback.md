# Runbook: Deploy và rollback

## Deploy

`scripts/deploy.ps1` thực hiện Compose config, image build/inspect, database wait, `alembic upgrade head`,
API wait và health smoke. Protected/public target phải dùng HTTPS, authentication, Secure cookie, managed
secret source, HTTPS CORS và non-default database password.

```powershell
.\scripts\deploy.ps1 -EnvironmentFile .env.local -ProjectName devradar -Image registry.example/devradar:<digest> -BaseUrl https://devradar.example -RequireHttps
```

Không đặt registry credential trong command history; dùng provider secret/identity.

## Rollback

1. Xác định image digest cuối cùng đã pass smoke và không có unresolved critical/high advisory.
2. Kiểm tra migration compatibility; không downgrade database tự động.
3. Chạy:

   ```powershell
   .\scripts\rollback.ps1 -EnvironmentFile .env.local -ProjectName devradar -Image registry.example/devradar:<known-good-digest> -BaseUrl https://devradar.example -RequireHttps
   ```

4. Kiểm tra health, login/session, owner scope, read API, alert disabled/allow-list và error rate.
5. Nếu rollback smoke fail, giữ traffic ở maintenance/previous known-good target và mở incident; không
   lặp deploy mù.
