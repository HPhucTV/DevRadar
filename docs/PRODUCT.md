# Product specification

## 1. Mục đích tài liệu

Tài liệu này định nghĩa **DevRadar cần giải quyết vấn đề gì và kết quả nào được xem là có giá trị**. Kiến trúc nằm trong [ARCHITECTURE.md](ARCHITECTURE.md), contract dữ liệu nằm trong [DOMAIN_MODEL.md](DOMAIN_MODEL.md), còn thứ tự triển khai nằm trong [ROADMAP.md](ROADMAP.md).

## 2. Tầm nhìn

DevRadar là nền tảng job-market intelligence dành trước hết cho sinh viên IT và developer tại Việt Nam. Nền tảng hợp nhất dữ liệu job công khai, giữ lịch sử thay đổi, phân tích nhu cầu kỹ năng và hỗ trợ người dùng so sánh hồ sơ của mình với thị trường.

Giá trị cốt lõi không nằm ở việc “crawl rồi gửi tất cả cho GPT”, mà ở ba lớp có thể kiểm chứng độc lập:

1. **Reliable data pipeline:** dữ liệu có provenance, idempotent, deduplicate và có lịch sử.
2. **Decision support:** trend, search và matching được tính từ dataset thật.
3. **Bounded intelligence:** LLM/agent chỉ bổ sung cho phần khó xác định, có validation và evaluation.

## 3. Người dùng

### 3.1. Primary persona — sinh viên IT hoặc junior developer

Nhu cầu chính:

- theo dõi internship, fresher và junior job từ nhiều nguồn;
- hiểu skill nào xuất hiện nhiều trong nhóm role mục tiêu;
- xem job mới hoặc job vừa thay đổi;
- biết CV đang match và thiếu gì so với job cụ thể;
- có dữ liệu thực tế để ưu tiên lộ trình học.

### 3.2. Secondary persona — developer có kinh nghiệm

Nhu cầu chính:

- lọc job theo role, level, location, salary và stack;
- theo dõi công ty hoặc nhóm công nghệ;
- xem xu hướng theo tuần/tháng;
- nhận alert khi có job phù hợp.

### 3.3. Không phải persona ban đầu

Recruiter, HR analytics, multi-tenant team và commercial data product không thuộc phạm vi ban đầu. Chúng chỉ được xem xét sau V6 bằng product decision mới.

## 4. Phạm vi sản phẩm

| Capability | Kết quả người dùng | Phase đầu tiên |
|---|---|---|
| Thu thập job từ nguồn đã duyệt | Có dataset thật, cập nhật được | V1 |
| Job explorer qua REST API | Tìm và lọc job chuẩn hóa | V1 |
| Lịch sử crawl và thay đổi | Biết job mới, đổi hoặc biến mất | V2 |
| Crawler health | Biết source nào đang lỗi hoặc stale | V2 |
| Skill extraction bằng LLM fallback | Biến JD phi cấu trúc thành dữ liệu có schema | V3 |
| Job classification và bounded AI summary | Phân loại role/level và tóm tắt có evidence | V3 |
| Skill trends và semantic search | Hiểu nhu cầu kỹ năng và tìm job gần nghĩa | V3 |
| Planner/validator/analyst agent | Tự điều chỉnh hoặc review ở điểm cần reasoning | V4 |
| Dashboard | Khám phá dữ liệu bằng giao diện web | V5 |
| CV matching | Xem match, missing skill và giải thích | V5 |
| Alert cá nhân | Nhận job mới thỏa tiêu chí | V5 |
| Public deployment an toàn | Cho người khác sử dụng có kiểm soát | V6 |

Mọi capability trong tài liệu ý tưởng ban đầu được ánh xạ vào bảng trên hoặc các non-goal bên dưới. “Đã có trong tầm nhìn” không đồng nghĩa “đã triển khai”.

### 4.1. Disposition của feature nâng cao trong idea

| Feature ý tưởng | Disposition hiện tại |
|---|---|
| Company Watchlist | V5, biểu diễn bằng `AlertRule` với company filter; không cần module riêng. |
| Salary Analytics | Candidate V5, chỉ mở khi salary coverage, currency và period quality đạt baseline được công bố. |
| AI Career Advisor | Candidate sau khi V5 matching được evaluation; advice phải dựa trên missing skill và market evidence. |
| Tech Stack Recommendation | Cùng capability với Career Advisor, không tạo agent/feature riêng trước khi có use case khác biệt. |
| Skill Graph | Post-V6 research candidate; không thuộc sáu phase đã cam kết vì chưa có requirement chứng minh graph storage/UI cần thiết. |
| Recruiter/HR benchmark | Ngoài phạm vi portfolio ban đầu; cần product/privacy decision mới. |

Các mục `Candidate` không phải deliverable hoặc acceptance criterion cho phase cho tới khi roadmap được cập nhật bằng evidence và quyết định cụ thể.

## 5. Use case và yêu cầu chức năng

### UC-01 — Ingest job

- Hệ thống thu thập từ `Source` đã được phê duyệt.
- Mỗi lần fetch tạo `RawJobSnapshot` có URL, thời gian, status và content hash.
- Dữ liệu hợp lệ được chuẩn hóa thành `Job` mà không làm mất raw value hoặc provenance.
- Rerun cùng input không tạo thêm `Job`, snapshot logic hoặc change event giả.

### UC-02 — Phát hiện thay đổi (V2)

- Hệ thống so sánh bản quan sát mới với canonical job hiện tại.
- Chỉ các field có ý nghĩa sản phẩm mới tạo `JobChange`.
- Job vắng mặt trong run lỗi hoặc partial không được đổi trạng thái.
- Người dùng có thể phân biệt `created`, `updated`, `missing` và `removed`; UI có thể hiển thị `created` bằng nhãn “new job”.

### UC-03 — Khám phá job và thị trường

- Người dùng lọc theo role/title, location, level, company, skill, salary và thời gian.
- Người dùng xem source URL, thời điểm quan sát và dữ liệu đã chuẩn hóa.
- Từ V3, người dùng xem skill frequency/trend trên một cohort và cửa sổ thời gian được công bố.

### UC-04 — Trích xuất dữ liệu phi cấu trúc

- Structured data và deterministic parser được dùng trước.
- Chỉ field còn thiếu hoặc độ tin cậy thấp mới được gửi qua LLM khi policy cho phép.
- Kết quả AI phải qua schema validation và giữ model/extractor version.
- Role/job classification và AI summary phải có evidence; summary không được thêm claim không có trong canonical input.
- Output không đạt yêu cầu được reject hoặc chuyển `needs_review`, không âm thầm trở thành dữ liệu chuẩn.

### UC-05 — CV matching

- Người dùng tải lên một file CV hợp lệ trong V5.
- Hệ thống trích xuất hồ sơ kỹ năng/kinh nghiệm, sau đó xóa file gốc theo mặc định.
- Match score gồm các thành phần được công bố; giải thích phải dựa trên evidence từ CV/JD.
- Người dùng thấy matched skill, missing skill và lý do, không chỉ một phần trăm tổng hợp.

### UC-06 — Agentic decision

- Planner có thể đề xuất ưu tiên crawl dựa trên metric thực, trong giới hạn policy xác định.
- Validator có thể accept, reject, retry hoặc yêu cầu review đối với extraction không chắc chắn.
- Analyst sinh insight từ aggregate/query result đã tính trước, không tự bịa số liệu.
- Mọi quyết định agent có input reference, output có schema, version, latency, cost và status.

### UC-07 — Alert

- Người dùng cấu hình tiêu chí job hoặc ngưỡng match.
- Alert chỉ gửi một lần cho cùng user/rule/job/version, trừ khi có thay đổi đủ điều kiện.
- Alert luôn liên kết về canonical job và source gốc.

## 6. Yêu cầu phi chức năng

| ID | Yêu cầu |
|---|---|
| NFR-01 | Ingestion phải idempotent và có thể replay từ fixture/raw snapshot. |
| NFR-02 | Mọi normalized field quan trọng phải có provenance hoặc raw value tương ứng. |
| NFR-03 | Source lỗi không được gây false removal hoặc làm hỏng dữ liệu đã có. |
| NFR-04 | Outbound crawler chỉ truy cập allow-list; timeout, redirect và response size phải bị giới hạn. |
| NFR-05 | Raw CV, secrets và token không xuất hiện trong application log, trace hoặc agent prompt log. |
| NFR-06 | LLM/agent output phải có schema validation, evaluation và fallback/review path. |
| NFR-07 | Metric đủ để trả lời mỗi run đã làm gì, thành công hay thất bại ở đâu và tốn bao nhiêu. |
| NFR-08 | Public mutation hoặc dữ liệu cá nhân phải có authentication/authorization trước khi deploy. |
| NFR-09 | Contract API đã phát hành không được phá vỡ nếu thiếu versioning hoặc migration plan. |
| NFR-10 | Project phải chạy local bằng tài nguyên phù hợp cho một portfolio; hạ tầng phân tán không là điều kiện V1. |

## 7. Product success criteria

### Mốc V1 đáng tin cậy

- ba source thật đã vượt source approval gate;
- toàn bộ inventory quan sát được từ tối thiểu ba approved source đã được ingest bằng current adapter version; latest runs complete và có inventory snapshot;
- canonical Job có identity 1:1 theo source/external ID, canonical URL và current raw snapshot;
- rerun cùng snapshot không tạo duplicate hoặc change giả;
- job lưu được title, company, source URL, `first_seen_at`, `last_seen_at`, raw snapshot reference và content hash;
- REST API đọc được job/source/run và filter cơ bản;
- có evidence cho một source success, một source fail và một parser regression fixture.

### Mốc analytics V3

- tối thiểu 500 canonical job records từ approved/reproducible runs, không tính fixture;
- cohort/source/time window và sample size được công bố khi demo semantic search hoặc trend;
- không diễn giải 78-job V1 inventory thành insight đại diện cho toàn thị trường Việt Nam.

### Mốc portfolio hoàn chỉnh

- tối thiểu 1.000 canonical job records từ ba source trở lên;
- scheduled crawling, change history và crawler health có bằng chứng vận hành;
- AI extraction có labeled evaluation set và báo cáo metric, không chỉ demo đẹp;
- trend và CV matching giải thích được dữ liệu đầu vào cùng công thức;
- dashboard, Docker deployment, CI gate, architecture diagram và demo video phản ánh đúng hệ thống đang chạy.

Các con số về accuracy/latency/cost cho V3–V6 không được bịa trước khi có baseline. Mỗi phase phải thiết lập baseline, ghi target trong roadmap/evaluation artifact rồi mới dùng target đó làm release gate.

## 8. Non-goals

- crawl site private, bypass CAPTCHA/auth/anti-bot hoặc vi phạm điều khoản;
- hỗ trợ 20+ source trong MVP;
- multi-country normalization, currency conversion hoặc tax/cost-of-living comparison ở V1;
- tự động apply job, gửi CV hoặc nhắn recruiter;
- recruiter ATS, employer posting hoặc commercial data resale;
- microservices, Kubernetes, Kafka, Pinecone/Qdrant hoặc distributed crawling nếu chưa có nhu cầu đo được;
- dùng LLM cho field deterministic parser đã lấy được đáng tin cậy;
- tuyên bố insight thị trường Việt Nam khi dataset chưa đủ hoặc cohort không được công bố.

## 9. Giả định sản phẩm

- Nội dung job có thể là tiếng Việt, tiếng Anh hoặc trộn hai ngôn ngữ.
- V1 giữ salary gốc và normalized amount/period/currency khi có thể; không tự quy đổi.
- Portfolio ban đầu là single-operator. Chức năng ghi dữ liệu nhạy cảm không được public trước V6.
- Ba source V1 đã được operator duyệt cho bounded local non-commercial scope: VNG Careers, NAVER Vietnam/Greenhouse và MoMo Careers. Mỗi adapter vẫn bị giới hạn bởi approval record/allow-list riêng; quyết định này không cấp quyền public full-JD, commercial reuse hoặc AI training. GeoComply/Lever giữ `permission_required` vì employer terms cấm automated retrieval.
