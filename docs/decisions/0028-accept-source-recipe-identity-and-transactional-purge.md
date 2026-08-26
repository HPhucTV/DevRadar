# ADR-028: Chấp nhận SourceRecipe identity dùng chung và transactional graph purge

## Status

Accepted

## Date

2026-08-26

## Context

`SourceRecipe` hiện có UUID, name, listing URL và lifecycle, nhưng operator khó đối chiếu recipe đang
vận hành với các run và recipe acceptance/test trong danh sách phẳng. `updated_at` chỉ phản ánh
config/lifecycle change, không chứng minh recipe vừa được preview/crawl/import.

`DELETE /api/v1/source-recipes/{recipeId}` đã phát hành với nghĩa retire: recipe/source chuyển `retired`
nhưng graph vẫn tồn tại để audit. Owner muốn thêm khả năng xóa vật lý toàn bộ recipe-derived graph khỏi
PostgreSQL. Đổi nghĩa endpoint DELETE hiện tại sẽ phá observable contract; xóa từng bảng không transaction
có thể để lại graph nửa vời, còn FK hiện hành chủ yếu `RESTRICT` nên database không tự cascade toàn bộ.

## Decision

### Identity

- Mọi recipe có display code deterministic `RCP-XXXXXXXX`, lấy tám hex đầu của UUID và không persist thêm.
- Mỗi exact normalized `listing_url` tiếp tục reuse một non-retired recipe; mỗi lần dùng tạo
  preview/run/import history mới thay vì recipe mới.
- `SourceRecipe` thêm nullable `last_used_at`; field được cập nhật khi bounded preview, crawl request hoặc
  document import được chấp nhận. Config-only PATCH không thay đổi field này.
- API thêm additive `lastUsedAt`; client cũ không bị yêu cầu gửi field mới.
- Dashboard có thể auto-select recipe bằng exact UUID query param và render cùng code/label. Presentation
  label không thay đổi raw `name` hoặc domain identity.

### Lifecycle và purge

- Giữ nguyên `DELETE /source-recipes/{recipeId}` là **Ngừng sử dụng**: chuyển recipe/source sang `retired`,
  dừng schedule/run mới và giữ audit graph.
- Thêm explicit owner-local purge command `POST /source-recipes/{recipeId}/purge` với body chứa exact
  `confirmationCode` bằng display code của recipe.
- Purge chỉ hợp lệ khi recipe đã `retired` và không còn preview/CrawlRun `pending|running`. Sai state trả
  `409` với safe code; sai confirmation trả `422`; cross-owner/missing trả generic `404`.
- Một PostgreSQL transaction xóa recipe, preview, source, run, snapshot, job, JobChange, extraction,
  embedding, JobMatch và AlertDelivery liên quan. ResumeProfile, AlertRule và source khác được giữ nguyên.
- Purge response trả counts theo entity để operator xác minh; không trả raw job/CV/HTML hoặc deleted data.
- Structured audit log chỉ chứa correlation ID, recipe/source ID và counts; không chứa raw content/URL
  query/PII.
- Purge không backup và không có undo theo quyết định explicit của owner.

## Alternatives considered

### Đổi DELETE hiện tại thành hard delete

Endpoint ngắn hơn nhưng silently phá retire/audit behavior đã phát hành và làm client cũ có thể xóa dữ
liệu ngoài ý muốn. Rejected.

### Chỉ xóa SourceRecipe row

Giữ jobs/history nhưng khiến UI “đã xóa” không tương ứng với database source graph và không đáp ứng yêu
cầu dọn sạch. Rejected.

### Dùng `updated_at` làm last-used signal

Không cần migration nhưng config edit/acknowledgement bị hiển thị như một run, còn successful import không
bắt buộc đổi config. Rejected vì semantics sai.

### Database cascade toàn bộ bằng migration FK

Đơn giản câu lệnh xóa nhưng mở rộng blast radius của mọi source/job delete, khó giữ ResumeProfile/AlertRule
và làm các delete path khác thay đổi ngoài requirement. Explicit transaction service được chọn.

## Consequences

- Purge implementation cần explicit delete order do composite/self-reference và `RESTRICT` FK.
- Client phải thực hiện retire trước purge và nhập confirmation code; UX dài hơn nhưng giảm accidental loss.
- `last_used_at` là lifecycle projection cần được cập nhật nhất quán ở preview/crawl/import entry points.
- Presentation label chỉ là projection UI; UUID và raw recipe name vẫn là domain identity.
