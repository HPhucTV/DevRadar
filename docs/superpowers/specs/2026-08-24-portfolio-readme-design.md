# DevRadar portfolio README design

## Mục tiêu

Viết lại `README.md` theo hướng portfolio-first để một nhà tuyển dụng có thể hiểu nhanh DevRadar giải quyết bài toán gì, sản phẩm trông như thế nào và độ sâu kỹ thuật nằm ở đâu. Cấu trúc lấy cảm hứng từ README showcase của SmartHire, nhưng nội dung, hình ảnh, câu chữ và nhận diện phải là của DevRadar.

README mới không thay đổi code, API, deployment hoặc phase roadmap. Tài liệu chi tiết và ADR tiếp tục là nguồn sự thật; README chỉ là entry point dễ đọc.

## Hướng đã chọn

Sử dụng phong cách **Evidence-led Editorial**:

- hero sáng, tinh gọn và có khoảng thở;
- tagline mô tả đúng pipeline dữ liệu và market intelligence;
- technology badge vừa đủ, không dùng badge trạng thái phase;
- số liệu portfolio chỉ lấy từ evidence đã commit;
- dùng ảnh chụp UI thật thay vì mockup hoặc hình minh họa bịa;
- architecture và Quick Start đủ ngắn để đọc tiếp trong một lần cuộn.

Không hiển thị nhãn `V6` trong README. Trạng thái được mô tả trung tính là active development; chi tiết phase nằm trong `docs/ROADMAP.md`.

## Đối tượng và ngôn ngữ

- Đối tượng chính: nhà tuyển dụng và người xem portfolio kỹ thuật.
- Đối tượng phụ: developer muốn chạy thử hoặc đọc kiến trúc.
- Nội dung chính viết bằng tiếng Việt; tên code, API, enum và thuật ngữ kỹ thuật giữ tiếng Anh.
- Giọng văn điềm tĩnh, cụ thể và evidence-backed; tránh các từ quảng cáo như “revolutionary”, “extreme” hoặc claim không đo được.

## Cấu trúc nội dung

1. **Hero**
   - `DevRadar` và một câu mô tả ngắn.
   - Badge cho Python/FastAPI, PostgreSQL/pgvector, Next.js, VI/EN và local-first AI.
   - Không có phase badge hoặc version badge.
2. **Verified snapshot**
   - `3,339` canonical jobs.
   - `3,339` current embeddings.
   - `1,003` accepted deterministic extraction results.
   - semantic held-out Top-1 `0.9583`.
   - Ghi rõ đây là snapshot đã được kiểm chứng, không phải số liệu realtime.
3. **Product showcase**
   - Một ảnh dashboard tổng quan làm ảnh chính.
   - Hai ảnh hỗ trợ cho analytics và operator/custom-source workflow nếu runtime thật có dữ liệu an toàn để chụp.
   - Mỗi ảnh có alt text và caption ngắn; README vẫn hiểu được khi ảnh không tải.
4. **Why DevRadar / capability groups**
   - Trustworthy ingestion.
   - Market intelligence.
   - Operator experience.
   - Privacy and safety boundaries.
5. **Architecture at a glance**
   - Mermaid flow đơn giản: source → ingestion → PostgreSQL → intelligence → FastAPI → Next.js.
   - Nêu modular monolith, deterministic-first và provenance.
6. **Tech stack**
   - Bảng ngắn theo layer; version chỉ ghi khi đang được khóa trong repository.
7. **Quick Start**
   - Clone, hash-locked Python install, Compose database/migration/API/web và health smoke.
   - Các flow opt-in như DeepSeek, CV, authentication và custom source chỉ link sang tài liệu chuyên biệt; không nhồi toàn bộ environment matrix vào README.
8. **Project map và documentation**
   - Cây thư mục ở mức module.
   - Link tới Product, Architecture, API, Ingestion, AI, Operations, Roadmap và ADR index.
9. **Safety boundary và footer**
   - Không bypass CAPTCHA, authentication, paywall hoặc anti-bot.
   - Custom source chỉ local/protected và owner-authorized.
   - Footer ngắn, không thêm license claim khi repository chưa có license tương ứng.

## Visual assets

Ảnh README được lưu dưới `docs/assets/readme/` và chụp từ local runtime hiện hành ở viewport desktop. Trước khi commit phải kiểm tra ảnh không chứa:

- token, secret, cookie hoặc URL có credential;
- raw CV, PII hoặc dữ liệu upload của người dùng;
- developer tooling, browser chrome hoặc overlay debug;
- trạng thái lỗi giả hoặc capability chưa hoạt động.

Không thêm banner AI-generated trong scope này. Hero dùng Markdown/HTML và badge; ảnh sản phẩm thật tạo điểm nhấn chính. Nếu một route không có dữ liệu an toàn để chụp, bỏ ảnh đó thay vì dựng dữ liệu gây hiểu nhầm.

## Bảo toàn contract và nguồn sự thật

- Không thay đổi `AGENTS.md`, ADR, API contract, domain lifecycle hoặc deployment gate.
- Không đổi trạng thái roadmap qua README.
- Claim kỹ thuật phải đối chiếu README hiện tại, `docs/ROADMAP.md` và evidence liên quan.
- Những hướng dẫn chi tiết bị rút khỏi README phải còn đường link rõ tới tài liệu nguồn; không xóa kiến thức vận hành khỏi repository.
- Không đưa `TASK_BOARD.md`, `.env*`, `.npm-cache/` hoặc visual-companion artifact vào commit.

## Verification và Definition of Done

- `README.md` không chứa nhãn `V6`.
- Mọi relative Markdown link và image path tồn tại; URL ngoài chỉ dùng cho badge hoặc nguồn tham khảo cần thiết.
- Mermaid dùng syntax được GitHub hỗ trợ và thể hiện đúng trust boundary.
- Các số liệu snapshot khớp evidence đã commit.
- Quick Start chỉ dùng command đã có trong `AGENTS.md` hoặc tài liệu operations.
- Ảnh được kiểm tra trực quan, có alt text và không lộ dữ liệu nhạy cảm.
- `git diff --check` sạch cho thay đổi mới.
- Narrow documentation checks và gate phù hợp chạy đến exit code cuối trước commit/push.
- Final Git status chỉ còn artifact user-owned đã có từ trước; `TASK_BOARD.md` vẫn ignored.

## Ngoài phạm vi

- Thay đổi UI application để phục vụ screenshot.
- Tạo logo hoặc brand identity mới.
- Thêm dependency, badge service tự vận hành hoặc documentation generator.
- Claim public deployment khi provider/public HTTPS evidence chưa hoàn tất.
- Sao chép banner, screenshot, câu chữ hoặc nhận diện của SmartHire.
