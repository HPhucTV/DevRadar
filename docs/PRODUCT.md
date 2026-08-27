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
| Tạo nguồn crawl từ listing URL | Không phải viết adapter; preview và kiểm tra trước khi chạy | V6-020 |
| Job explorer qua REST API | Tìm và lọc job chuẩn hóa | V1 |
| Lịch sử crawl và thay đổi | Biết job mới, đổi hoặc biến mất | V2 |
| Crawler health | Biết source nào đang lỗi hoặc stale | V2 |
| Skill extraction bằng LLM fallback | Biến JD phi cấu trúc thành dữ liệu có schema | V3 |
| Job classification và bounded AI summary | Phân loại role/level và tóm tắt có evidence | V3 |
| Skill trends và semantic search | Hiểu nhu cầu kỹ năng và tìm job gần nghĩa | V3 |
| Planner/validator/analyst evaluation | Đánh giá reasoning path so với deterministic baseline; cả ba bị loại vì không có measurable gain | V4 — complete/removed |
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

- Operator local dán một HTTPS listing URL, chọn seniority và lưu thành `SourceRecipe`; request crawl
  không nhận URL/config override theo từng run.
- Lựa chọn nguồn nằm ngoài phạm vi đánh giá pháp lý của DevRadar; hệ thống không đưa ra permission hoặc
  legal certification và chỉ áp dụng technical policy theo [ADR-029](decisions/0029-remove-source-terms-acknowledgement-retain-technical-barriers.md).
- Preview dùng structured data/HTTP trước, isolated Playwright fallback sau; cần 3–5 candidate hợp lệ
  hoặc visual mapping trước khi recipe được `enabled`.
- CAPTCHA, authentication, paywall, anti-bot, access denial, SSRF hoặc redirect escape luôn dừng ở
  `blocked`; không có UI hoặc config để override technical barrier.
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

### UC-06 — Agentic decision evaluation (V4 closed)

- Planner, validator và analyst được so sánh với deterministic V2/V3 baseline bằng safety/usefulness gate đặt trước.
- Scripted workflow chứng minh schema/policy/failure boundary nhưng không chứng minh model usefulness.
- Cả ba reasoning path bị loại theo ADR-013 vì input facts đã xác định outcome và không có labeled measurable gain.
- Future agent use case cần frozen labeled dataset, improvement target, privacy boundary và ADR mới; không có current agent runtime.

### UC-07 — Alert

- Người dùng cấu hình tiêu chí job hoặc ngưỡng match.
- Alert chỉ gửi một lần cho cùng user/rule/job/version, trừ khi có thay đổi đủ điều kiện.
- Alert luôn liên kết về canonical job và source gốc.
- V5-006 chỉ mở local/protected với một Discord webhook operator-owned; rule có
  company/skill literal hoặc ngưỡng `JobMatch`, dispatch tối đa 20 job/lần.
- Webhook secret nằm ngoài database/log; delivery retry/replay phải giữ
  idempotency key và không tạo duplicate cho cùng job content revision.

## 6. Yêu cầu phi chức năng

| ID | Yêu cầu |
|---|---|
| NFR-01 | Ingestion phải idempotent và có thể replay từ fixture/raw snapshot. |
| NFR-02 | Mọi normalized field quan trọng phải có provenance hoặc raw value tương ứng. |
| NFR-03 | Source lỗi không được gây false removal hoặc làm hỏng dữ liệu đã có. |
| NFR-04 | Outbound crawler chỉ truy cập allow-list; timeout, redirect và response size phải bị giới hạn. |
| NFR-05 | Raw CV, secrets và token không xuất hiện trong application log, trace hoặc model prompt log. |
| NFR-06 | LLM output phải có schema validation, evaluation và fallback/review path. Future agent output phải đạt thêm gate ADR-013. |
| NFR-07 | Metric đủ để trả lời mỗi run đã làm gì, thành công hay thất bại ở đâu và tốn bao nhiêu. |
| NFR-08 | Public mutation hoặc dữ liệu cá nhân phải có authentication/authorization trước khi deploy. |
| NFR-09 | Contract API đã phát hành không được phá vỡ nếu thiếu versioning hoặc migration plan. |
| NFR-10 | Project phải chạy local bằng tài nguyên phù hợp cho một portfolio; hạ tầng phân tán không là điều kiện V1. |

## 7. Product success criteria

### Mốc V1 đáng tin cậy

- source/run fixture đã chứng minh fetch boundary, provenance và PostgreSQL migration;
- mọi inventory claim chỉ dùng run complete, có cohort/source label và evidence tương ứng;
- canonical Job có identity 1:1 theo source/external ID, canonical URL và current raw snapshot;
- rerun cùng snapshot không tạo duplicate hoặc change giả;
- job lưu được title, company, source URL, `first_seen_at`, `last_seen_at`, raw snapshot reference và content hash;
- REST API đọc được job/source/run và filter cơ bản;
- có evidence cho một recipe success, một recipe fail/challenge và một parser regression fixture.

### Mốc analytics V3

- tối thiểu 500 canonical job records từ approved/reproducible runs, không tính fixture;
- cohort/source/time window và sample size được công bố khi demo semantic search hoặc trend;
- không diễn giải 78-job V1 inventory thành insight đại diện cho toàn thị trường Việt Nam.

### Mốc portfolio hoàn chỉnh

- dataset demo công bố đúng cohort, sample size và thời điểm; không dùng con số lịch sử như realtime;
- scheduled crawling, change history và crawler health có bằng chứng vận hành;
- AI extraction có labeled evaluation set và báo cáo metric, không chỉ demo đẹp;
- trend và CV matching giải thích được dữ liệu đầu vào cùng công thức;
- dashboard, Docker deployment, CI gate, architecture diagram và demo video phản ánh đúng hệ thống đang chạy.

Các con số về accuracy/latency/cost cho V3–V6 không được bịa trước khi có baseline. Mỗi phase phải thiết lập baseline, ghi target trong roadmap/evaluation artifact rồi mới dùng target đó làm release gate.

## 8. Non-goals

- crawl site private hoặc bypass CAPTCHA/auth/paywall/anti-bot/access control;
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
- Portfolio ban đầu là single-operator. Source Recipe chỉ chạy trong `LOCALHOST_SERVICE`; chức năng ghi
  dữ liệu nhạy cảm không được public nếu chưa qua auth/privacy gate.
- Catalog mười nguồn chỉ là shortcut URL, không phải adapter, permission, legal assessment hay cam kết
  nguồn sẽ crawl thành công. Catalog và URL ngoài catalog đi qua cùng technical access barrier fail-closed.
