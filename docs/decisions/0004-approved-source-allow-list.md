# ADR-004: Chỉ crawl source đã duyệt qua allow-list

## Status

Accepted

## Date

2026-08-21

## Context

Crawler truy cập hệ thống bên ngoài và xử lý nội dung không đáng tin. URL do user/model kiểm soát tạo rủi ro SSRF; crawl site cấm hoặc cần bypass control tạo rủi ro policy, vận hành và uy tín portfolio. Source layout/identity không ổn định cũng có thể tạo duplicate hoặc false removal.

Ba source V1 chưa được chọn, vì việc chọn cần review thông tin hiện hành về quyền truy cập, robots/terms và cấu trúc kỹ thuật.

## Decision

- Mọi source bắt đầu ở `candidate` và chỉ chạy live khi `approval_status=approved` theo gate trong [Ingestion specification](../INGESTION.md).
- Source registry chứa base/allowed hosts, adapter key, identity, pagination/coverage và fetch policy đã version.
- API/model không được truyền arbitrary URL, host, header, adapter path hoặc credential vào crawler.
- Mỗi redirect được revalidate; private/reserved destination, host ngoài allow-list, response quá lớn/chậm hoặc content type không hỗ trợ bị chặn.
- Không bypass CAPTCHA, authentication, anti-bot, paywall hoặc access control.
- Source có terms/policy mơ hồ được giữ `candidate/paused`; thay đổi terms hoặc hành vi bất thường có thể quarantine/pause ngay.
- Browser chỉ được dùng khi approved source cần JavaScript và HTTP/structured extraction không đủ.

## Alternatives considered

### Nhận URL tùy ý từ user

Rejected vì mở SSRF, uncontrolled resource use, policy violation và parser surface không bounded.

### Chọn job aggregator phổ biến rồi xử lý anti-bot khi gặp

Rejected vì “bypass sau” không phải source strategy hợp lệ và làm project phụ thuộc vào hành vi dễ vi phạm/thay đổi.

### Chỉ dùng fixture, không crawl nguồn thật

Rejected cho mục tiêu portfolio vì không chứng minh ingestion trên dữ liệu/live failure thực. Fixture vẫn bắt buộc cho test, nhưng không thay ba approved source.

### Cho agent tự discover và approve source

Rejected vì policy/terms/risk review cần human/operator decision; model không có thẩm quyền mở trust boundary.

## Consequences

### Positive

- outbound surface bounded và dễ test/audit;
- source identity/completeness được xác minh trước khi ảnh hưởng dữ liệu;
- project thể hiện crawling có trách nhiệm thay vì kỹ thuật bypass;
- source có thể pause/quarantine mà không xóa lịch sử.

### Trade-offs

- source onboarding cần review thủ công và evidence;
- số source tăng chậm hơn crawler generic;
- source terms/layout cần được review lại định kỳ.

### Required follow-up

- Pre-V1 chọn và ghi approval record cho ba source thật trước khi code adapter.
- V1 có negative test cho unapproved source, redirect escape, private/reserved IP, timeout và response size.
- Public deployment phải có takedown/contact process và lịch review source policy.

