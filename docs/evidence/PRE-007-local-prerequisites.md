# PRE-007: Local prerequisites evidence

**Checked at:** 2026-08-21T16:20:27+07:00

**Host:** Windows 11 Pro 64-bit, build 26200

**Result:** `pass_with_constraints`

## 1. Kết luận

Máy local đủ capability để bắt đầu V1 scaffold với Docker Compose và PostgreSQL thật. Docker daemon/Compose hoạt động, PostgreSQL 18.4 đang chạy và trả `accepting connections` trên loopback.

Không có project database, role, credential, migration hoặc application connection nào được kiểm tra vì DevRadar chưa scaffold. PRE-007 không cài package, không pull image, không start/stop container/service và không sửa trạng thái máy.

## 2. Evidence

| Capability | Kết quả xác minh |
|---|---|
| Shell | PowerShell 7.6.4 |
| Docker Desktop | 4.55.0 (213807) |
| Docker client/engine | 29.1.3, API 1.52 |
| Docker context | `desktop-linux` |
| Container OS/arch | Linux/amd64 |
| Docker Compose | v2.40.3-desktop.1 |
| Docker resources | 20 CPUs, 8,129,785,856 bytes memory |
| Workspace disk | 102.34 GiB free trên drive C tại thời điểm check |
| PostgreSQL service | `postgresql-x64-18`, `Running`, startup `Automatic` |
| PostgreSQL binaries | `psql`, `pg_isready`, `postgres` version 18.4 |
| PostgreSQL readiness | `127.0.0.1:5432 - accepting connections`, exit 0 |
| Cached PostgreSQL images | `postgres:16`, `postgres:16-alpine`, `postgres:16.4-alpine` |
| Running PostgreSQL containers | Không có |

## 3. Commands đã chạy thành công

Các command dưới đây chỉ là diagnostic evidence trên máy review, chưa phải DevRadar Quick Start:

```powershell
docker version
docker compose version
docker context show
docker info
docker system df
Get-Service -Name postgresql-x64-18
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' --version
& 'C:\Program Files\PostgreSQL\18\bin\pg_isready.exe' -h 127.0.0.1 -p 5432 -t 3
```

Không thêm các command này vào README/AGENTS như project command vì chưa có Compose file, database config hoặc migration để chúng vận hành DevRadar.

## 4. Constraints cần giữ khi scaffold V1

### Port

Host port `5432` đang được PostgreSQL 18.4 sử dụng trên `127.0.0.1` và `::1`. V1 Compose không được mặc định bind `0.0.0.0:5432` hoặc chiếm port này.

Giải pháp nhỏ nhất khi scaffold là bind database container vào loopback với một host port cấu hình riêng, ví dụ `127.0.0.1:55432`, trong khi container vẫn dùng port 5432 nội bộ. Port cụ thể chỉ được khóa sau khi Compose smoke chạy thành công.

### PostgreSQL major version

Local service là 18.4 nhưng các image cache hiện có thuộc major 16. PRE-007 không chọn major thay cho scaffold task. `V1-001/V1-002` phải:

1. chọn và pin một supported PostgreSQL image/major;
2. chạy migration/integration test trên đúng image đó;
3. ghi version và commands đã pass vào README/AGENTS;
4. không gọi test trên local service hoặc image major khác là evidence tương đương.

### Client path và credentials

`psql` và `pg_isready` không nằm trong `PATH`; bare command thất bại. Scaffold không được giả định global client tồn tại. Dùng containerized project command hoặc documented absolute/tool-managed path sau khi cách đó được chạy thành công.

Không có `PG*`/`POSTGRES*` environment variable trên host và không xác minh credential/database của local service. DevRadar phải tạo project-scoped database/role qua cấu hình riêng, không tái sử dụng database hoặc credential của project khác.

### Isolation

- Các stopped container/volume/image hiện có thuộc project khác và không được dọn hoặc tái sử dụng.
- Compose resource name/volume phải scoped cho DevRadar.
- Database chỉ bind loopback ở V1; không public port ra LAN.
- Teardown mặc định không xóa volume; destructive cleanup phải là command tách biệt và explicit.

## 5. Boundary chưa kiểm thử

- chưa pull hoặc chạy image PostgreSQL mới;
- chưa tạo DevRadar database/role;
- chưa kiểm tra SQL connection/authentication;
- chưa chạy migration, FastAPI, test hoặc Docker Compose của DevRadar;
- chưa kiểm tra pgvector vì thuộc V3.

Các boundary này thuộc `V1-001`, `V1-002` và các task sau, không phải failure của PRE-007.
