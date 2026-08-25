# ADR-027: Đề xuất local document import với incomplete coverage

## Status

Proposed

## Date

2026-08-25

## Context

Một số trang listing công khai hiển thị trong browser của operator nhưng trả access denial cho HTTP/TLS
client của DevRadar. ADR-026 yêu cầu dừng remote preview/crawl trước `401/403`, CAPTCHA, login, paywall
hoặc anti-bot và không cho phép URL/header/cookie/proxy override. Operator vẫn cần đưa dữ liệu họ đã mở
và lưu cục bộ vào pipeline mà không biến DevRadar thành fetch proxy.

## Proposed decision

Cho phép local document import gắn với persisted `SourceRecipe`:

- chỉ hoạt động trong cùng localhost/source-recipe feature gate và mutation security boundary;
- nhận bounded UTF-8 HTML, JSON hoặc CSV; không nhận URL/header/cookie/credential/proxy/code;
- không render, execute hoặc thực hiện outbound request từ nội dung upload;
- candidate URL phải là public-form HTTPS URL trên đúng recipe origin host;
- file gốc không được persist hoặc log; snapshot giữ canonical candidate, field provenance, media type và
  SHA-256 của document;
- import tái sử dụng canonical ingestion/idempotency nhưng coverage luôn `incomplete`;
- import không thay đổi recipe preview/block/enable lifecycle và không thể bật remote crawler;
- browser preview abort unapproved subresource mà không false-block toàn trang; unapproved navigation,
  redirect và SSRF signal vẫn hard stop.

Thiết kế chi tiết: [Local Document Import and Safe Browser Routing](../superpowers/specs/2026-08-25-local-document-import-design.md).

## Alternatives considered

### Persist upload rồi xử lý qua queue

Cho retry và request ngắn hơn nhưng cần entity, migration, retention/cleanup và raw-file storage chưa có
measured need. Không chọn cho bounded no-network input.

### Browser extension gửi DOM hiện tại

UX tốt hơn nhưng thêm extension permission/distribution và session boundary. Defer tới khi file-import
pipeline có acceptance evidence.

### One-shot URL fetch

Vẫn bị access denial, trùng remote recipe crawler và mở lại SSRF/per-run override. Rejected.

## Consequences

- Operator có đường nhập dữ liệu thủ công khi remote crawler bị chặn, nhưng không có auto schedule hoặc
  completeness/removal detection từ file import.
- Một file chỉ cung cấp field hiện diện trong file; detail không được tải bổ sung.
- HTML/CSV/JSON là untrusted input nên cần strict size/complexity/type bounds và negative tests.
- ADR chỉ chuyển `Accepted` sau khi product owner review written spec; chưa cho phép implementation khi
  còn `Proposed`.
