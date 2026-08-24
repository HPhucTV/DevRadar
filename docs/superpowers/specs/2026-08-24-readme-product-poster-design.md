# DevRadar README product poster design

## Context

README portfolio hiện dùng ba screenshot full-page. Khi GitHub thu chúng về chiều rộng khoảng 800–900px, chữ trong ảnh quá nhỏ, section kéo dài và ba ảnh cạnh tranh thị giác thay vì kể một câu chuyện sản phẩm.

Thiết kế này thay riêng phần Product Showcase. Hero, verified snapshot, architecture, Quick Start, documentation và safety boundary của README không đổi.

## Direction

Tạo một **Branded Product Poster** tỷ lệ `16:9`, kích thước `1600×900`, theo bố cục bento. Poster kết hợp:

- một background radar/data mesh do built-in image generation tạo;
- crop từ UI DevRadar thật;
- chữ, metric, card và data flow dựng xác định bằng HTML/CSS;
- một PNG cuối dùng trực tiếp trong README.

AI chỉ tạo atmosphere. AI không được tạo chữ, logo, số liệu, dashboard hoặc capability.

## Composition

### Left narrative column

Chiếm khoảng 36–40% chiều rộng:

- wordmark `DevRadar`;
- eyebrow `EVIDENCE-LED JOB MARKET INTELLIGENCE`;
- headline `Từ job posting đến tín hiệu thị trường có thể kiểm chứng.`;
- bốn metric card:
  - `4` data sources;
  - `23` tracked skills;
  - `1,003` analyzed jobs;
  - `0.9583` semantic held-out Top-1.

Metric là verified snapshot, không phải counter realtime. `1,003` và `0.9583` truy về `docs/evidence/V3-006-v3-closeout.md`; `4` và `23` khớp dashboard/runtime hiện hành.

### Right product bento

Chiếm khoảng 60–64% chiều rộng và dùng ba crop UI thật:

1. dashboard overview/skill demand làm panel chính;
2. analytics taxonomy/trend làm panel phụ;
3. custom source safety/form làm panel phụ.

Crop tập trung vào chart, KPI và bounded workflow. Không hiển thị browser chrome, header version badge, footer, khoảng trắng dài hoặc field chứa dữ liệu người dùng.

### Bottom data ribbon

Một ribbon ngắn dùng text xác định:

`Sources → Safe ingestion → PostgreSQL → Intelligence → Dashboard`

Ribbon chỉ tóm tắt data flow đã có trong `docs/ARCHITECTURE.md`; không thêm component mới.

## Visual language

- Background: off-white editorial, radar rings và data constellation rất nhẹ.
- Foreground: navy đậm, indigo và cyan; amber chỉ dùng cho một điểm nhấn nhỏ nếu cần.
- Typography: Georgia cho display headline, Segoe UI cho body/metric; mọi chữ render qua browser, không qua image generation.
- Card: radius vừa, border mảnh, shadow thống nhất; không glassmorphism nặng.
- Không emoji, không stock icon, không `V6`, không logo bên thứ ba, không watermark.
- Mọi text quan trọng phải còn đọc được khi poster hiển thị ở chiều rộng GitHub khoảng `838px`; source body text không nhỏ hơn `24px`.

## Image-generation boundary

Built-in `image_gen` tạo một background preview với prompt dạng `productivity-visual`:

- abstract radar field và data mesh;
- wide landscape composition;
- palette off-white, navy, indigo, cyan;
- subtle editorial/data-intelligence mood;
- không text, number, logo, UI, people hoặc watermark.

Generated background là supporting input, không phải sản phẩm cuối. Nếu built-in generation không dùng được hoặc output không đạt, fallback là CSS gradient/radar code-native; không chuyển sang CLI/API và không yêu cầu API key nếu chưa có xác nhận mới của người dùng.

## Build flow

1. Tạo background bằng built-in `image_gen` và kiểm tra visual.
2. Dùng các screenshot UI thật hiện có hoặc recapture bounded DOM region nếu crop hiện tại không đủ rõ.
3. Dựng poster trong một HTML/CSS artifact dưới thư mục ignored `output/readme-poster/`.
4. Dùng Playwright/installed Edge chụp đúng `1600×900` thành preview PNG.
5. Kiểm tra preview ở original size và GitHub-like width.
6. Hiển thị preview cho người dùng; chưa sửa README và chưa xóa asset cũ ở bước này.
7. Chỉ sau khi người dùng duyệt preview:
   - lưu final thành `docs/assets/readme/devradar-product-poster.png`;
   - thay Product Showcase bằng một image + caption ngắn;
   - xóa `dashboard-overview.png`, `analytics.png`, `sources.png`;
   - verify và push.

## Accessibility and truthfulness

- Alt text mô tả poster là composite của dashboard, analytics và custom-source workflow.
- Verified metrics vẫn tồn tại dưới dạng text trong README; poster không phải nguồn duy nhất truyền tải số liệu.
- Architecture data flow vẫn tồn tại trong Mermaid/text; ribbon không phải nguồn duy nhất.
- Không chỉnh UI crop để che lỗi hoặc dựng state không tồn tại.
- Không log/capture token, cookie, raw CV, PII hoặc custom URL thật.
- Poster không claim public deployment, realtime telemetry hoặc AI capability ngoài evidence hiện hành.

## Definition of Done

- Preview và final đúng `1600×900`.
- Không có generated text/UI trong background.
- Không có `V6`, secret, PII, browser chrome, loading/error state hoặc watermark.
- Ba capability chính nhận biết được trong một lần nhìn; chữ chính đọc được ở GitHub width.
- Final PNG nhỏ hơn `1.5MB`.
- README chỉ tham chiếu poster mới; ba asset full-page cũ bị xóa sau preview approval.
- Relative image/link check, no-version check, `tests/test_custom_source_docs.py`, secret scan và `git diff --check` pass.
- GitHub-rendered README load poster với natural size `1600×900`.
- `TASK_BOARD.md` và `.npm-cache/` không được commit.

## Out of scope

- Sửa giao diện application chỉ để tạo poster.
- Tạo logo/brand identity mới.
- Thay đổi metric, API, roadmap, ADR hoặc deployment claim.
- Video, GIF, animation hoặc external image hosting.
- Giữ generated background như một asset độc lập trong README.
