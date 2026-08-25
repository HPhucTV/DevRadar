# One-click Docker Desktop launcher design

**Date:** 2026-08-25

**Status:** Approved for planning

**Scope:** Windows localhost launcher only

## Context

DevRadar đã có `start-devradar.cmd` gọi `scripts/start-devradar.ps1`. Launcher hiện build ba image,
khởi động PostgreSQL, chạy migration, bật API/web/crawler, chạy smoke và mở dashboard. Tuy nhiên nó yêu
cầu Docker Desktop đã chạy; khi Docker CLI có mặt nhưng engine chưa sẵn sàng, người dùng chỉ nhận lỗi
Compose thay vì một one-click flow hoàn chỉnh.

## Decision

Nâng cấp PowerShell launcher hiện tại. Không tạo installer, executable wrapper, Windows service hoặc
dependency mới.

Khi double-click `start-devradar.cmd`, launcher phải:

1. kiểm tra Docker CLI tồn tại;
2. gọi `docker info` để xác định engine đã sẵn sàng hay chưa;
3. nếu engine chưa sẵn sàng, tìm Docker Desktop tại các đường dẫn cài đặt Windows được hỗ trợ;
4. mở Docker Desktop nếu process chưa chạy, hoặc chỉ chờ nếu process đã chạy;
5. poll `docker info` với khoảng chờ ngắn và timeout tổng cộng 180 giây;
6. sau khi engine sẵn sàng, tiếp tục nguyên flow build → database → migration → API/web/crawler → smoke
   → mở dashboard.

## Supported discovery boundary

Launcher chỉ kiểm tra các vị trí cài đặt local rõ ràng, bắt đầu từ đường dẫn Docker Desktop chuẩn dưới
`Program Files`, sau đó là vị trí per-user dưới `LOCALAPPDATA` nếu tồn tại. Không quét toàn ổ đĩa, không
đọc shortcut tùy ý và không sửa `PATH` hoặc registry.

Nếu Docker CLI không tồn tại hoặc không tìm được Docker Desktop, launcher dừng với thông báo cụ thể:
cài Docker Desktop hoặc mở thủ công rồi chạy lại. Nếu engine không ready trong 180 giây, launcher dừng
với timeout và giữ cửa sổ CMD mở để người dùng đọc lỗi.

Docker Desktop là ứng dụng tương tác mà người dùng có thể cần xem để chấp nhận điều khoản, cập nhật hoặc
xử lý lỗi; launcher không ép ẩn cửa sổ của nó.

## State and safety

- Nếu `docker info` đã pass, launcher không mở thêm Docker Desktop và không chờ thừa.
- Nếu process Docker Desktop đã tồn tại nhưng engine chưa ready, launcher không tạo process trùng.
- `.env` chỉ được copy từ `.env.example` khi chưa tồn tại.
- Các process environment flag localhost được khôi phục trong `finally` như hiện tại.
- Không yêu cầu quyền administrator, không gọi `Start-Service`, không thay Docker configuration.
- Không xóa volume, database hoặc file; không tự enable recipe và không tự crawl URL.
- Lỗi preflight phải giữ nguyên nguyên nhân hữu ích nhưng không in secret hoặc toàn bộ environment.

## User feedback

Trong thời gian chờ, launcher in thông báo Docker Desktop đang được mở hoặc đang khởi động và cập nhật
thời gian đã chờ theo nhịp bounded. Sau khi ready, output chuyển rõ sang bước khởi động DevRadar. Kết quả
thành công vẫn là dashboard `http://127.0.0.1:3000` được mở sau API/web smoke.

## Verification design

### Automated regression

Mở rộng `tests/test_deployment_scripts.py` theo TDD để khóa các contract sau:

- `docker info` được kiểm tra trước bất kỳ lệnh `docker compose` nào;
- có discovery `Docker Desktop.exe`, process guard, `Start-Process`, bounded poll và timeout 180 giây;
- nhánh engine-ready không launch Docker Desktop;
- không dùng Windows service/admin, không xóa volume và không tự crawl;
- lỗi vẫn truyền exit code khác 0 về CMD để cửa sổ được pause.

Static launcher contract phù hợp convention hiện tại; verification runtime bổ sung bằng actual PowerShell
parse, launcher test suite và one-click smoke trên Docker Desktop thật.

### Runtime acceptance

1. Parse PowerShell script không có syntax error.
2. Với Docker engine đang ready, chạy `start-devradar.cmd`; launcher không tạo Docker Desktop process mới,
   Compose/migration/smoke pass và dashboard mở được.
3. Xác minh API health và web `/sources` sau launcher.
4. Chạy launcher lần hai để chứng minh idempotent startup: không xóa volume, không tạo `.env` mới và stack
   vẫn healthy.

Việc cố ý tắt hoặc kill Docker Desktop không thuộc acceptance mặc định vì có thể làm gián đoạn container
khác trên máy. Auto-start branch được khóa bằng regression contract và bounded preflight logic; nếu có
môi trường Windows sạch dành riêng, có thể chạy thêm manual cold-start evidence.

## Documentation changes

README Quick Start sẽ nói rõ launcher tự mở/chờ Docker Desktop khi cần, timeout và yêu cầu Docker Desktop
đã được cài đặt. `docs/OPERATIONS.md` ghi failure messages và manual fallback. Không tạo ADR mới vì đây là
cải tiến vận hành có thể đảo ngược, không thay architecture hoặc public API.

## Non-goals

- tự cài hoặc tự cập nhật Docker Desktop;
- bypass Docker license/login/update prompts;
- hỗ trợ WSL-only engine, Podman hoặc Linux/macOS launcher trong task này;
- đóng gói `.exe`, tạo desktop shortcut hoặc chạy DevRadar khi Windows boot;
- thay đổi Compose topology, authentication, source policy hoặc ingestion behavior.

## Acceptance criteria

- Người dùng đã cài Docker Desktop có thể double-click duy nhất `start-devradar.cmd` khi engine đang tắt
  hoặc đang khởi động và launcher sẽ tự mở/chờ engine trong bounded timeout.
- Engine ready đi thẳng vào current startup flow mà không launch process trùng.
- Missing CLI, missing Desktop và timeout đều có thông báo actionable cùng exit code khác 0.
- Automated launcher/docs tests, PowerShell parse, Compose config, API smoke và web smoke pass.
- README không tuyên bố auto-install Docker hoặc hỗ trợ platform chưa kiểm chứng.
