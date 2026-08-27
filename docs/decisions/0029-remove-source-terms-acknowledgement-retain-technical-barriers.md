# ADR-029: Loại source terms acknowledgement, giữ technical access barriers

## Status

Accepted

## Date

2026-08-27

## Context

ADR-026 tách website terms notice khỏi technical access barrier nhưng vẫn bắt SourceRecipe lưu
version/evidence/review state và yêu cầu owner acknowledgement trong một số flow. Contract đó trải qua
schema, API, scheduler, document import và dashboard, trong khi acknowledgement không cấp permission,
không chứng minh quyền truy cập và không thay đổi bất kỳ barrier kỹ thuật nào.

Trong vận hành localhost single-operator, terms surface gây thêm trạng thái và thao tác nhưng không tạo
thêm technical safety. Owner quyết định không dùng DevRadar để review, diễn giải hoặc xác nhận điều khoản
nguồn. Trách nhiệm chọn nguồn thuộc operator; DevRadar chỉ thực thi ranh giới kỹ thuật có thể kiểm chứng.

Một vấn đề UX liên quan cũng được xác minh: document import đã persist Job thành công nhưng completion CTA
dẫn operator về SourceRecipe management thay vì Jobs explorer. Dữ liệu tồn tại trong PostgreSQL và Jobs
API, nhưng bề mặt điều hướng làm nó trông như không xuất hiện.

## Decision

### Source terms hard cut

- Xóa terms notice, terms version/evidence/review và acknowledgement khỏi SourceRecipe runtime, schema,
  REST/OpenAPI, scheduler, document import, dashboard và current documentation.
- SourceRecipe create/patch không nhận acknowledged notice version; response không trả terms fields.
- Preview thành công tự chuyển sang trạng thái sẵn sàng. Không có acknowledgement step, command hoặc error.
- Enable, manual/scheduled run và document import chỉ phụ thuộc lifecycle, successful preview/config,
  cooldown/quarantine và technical policy; không phụ thuộc legal/terms state.
- Source catalog có thể giữ bounded URL shortcut nhưng không giữ hoặc phát hành terms review/evidence.
- Xóa Source-level terms review timestamp/response field; approved-source technical check chỉ còn yêu cầu
  robots review timestamp. Robots/access-control policy không bị gỡ.
- Privacy contract không mô tả acknowledgement như owner override.

### Technical barriers remain mandatory

Không thay đổi các gate sau:

- HTTPS/exact host/path và SSRF/DNS/IP/redirect policy;
- CAPTCHA, login, paywall, anti-bot, access denial và route escape hard stop;
- item/page/request/byte/time/rate budgets, sequential processing và no arbitrary fetch proxy;
- provenance, idempotency, incomplete-coverage/false-removal protections;
- owner-local feature gate và protected/public deployment restrictions.

### Post-import visibility

- Document import response trả source ID cùng CrawlRun/counters.
- Jobs explorer nhận bounded sourceId query và chuyển nó tới existing read-only Jobs API filter.
- Source workflow hiển thị CTA dẫn tới đúng Jobs result sau import thành công.
- Client không có source ID được phép mở Jobs explorer theo sort mới nhất; không suy đoán ID hoặc URL.

### Migration and history

- Forward Alembic migration chỉ loại terms-related columns/constraints; không reset Source, Job,
  RawJobSnapshot, CrawlRun hoặc SourceRecipe identity.
- Worker phải dừng trong migration/deploy để không claim config chứa schema cũ.
- ADR/source-review evidence lịch sử được giữ để audit, nhưng không còn là active runtime contract.

ADR này supersede phần terms notice/acknowledgement của ADR-026. ADR-026 vẫn có hiệu lực cho
owner-local SourceRecipe, generic no-code ingestion và technical no-bypass boundary.

## Alternatives considered

### Chỉ ẩn terms UI

Backend vẫn chặn preview/import/schedule bằng acknowledgement nên operator tiếp tục gặp failure không
giải thích được. Rejected vì không phải hard cut.

### Auto-acknowledge mọi recipe

Giữ schema và error taxonomy nhưng tạo dữ liệu acknowledgement giả không phản ánh hành động người dùng.
Rejected vì semantics sai và tăng maintenance.

### Giữ một confirmation trung tính

Preview vẫn cần thêm một click dù technical validation đã hoàn tất. Owner đã chọn preview thành công tự
ready, nên confirmation riêng không còn yêu cầu hiện tại.

## Consequences

- Wire contract SourceRecipe và Privacy thay đổi có chủ ý; OpenAPI/code/tests/docs phải cập nhật cùng
  migration.
- Existing terms fields bị xóa vật lý và không thể đọc lại từ active schema; source-derived data không bị
  ảnh hưởng.
- Operator có ít thao tác và trạng thái hơn, nhưng DevRadar không đưa ra legal/permission assessment.
- Technical barriers trở thành ranh giới duy nhất của crawler và tiếp tục fail closed.
- Completion flow đưa người dùng tới dữ liệu đã persist thay vì chỉ quay lại recipe management.
