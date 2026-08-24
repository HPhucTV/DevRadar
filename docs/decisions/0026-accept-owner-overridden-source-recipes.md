# ADR-026: Chấp nhận no-code SourceRecipe owner-local với terms notice có thể xác nhận

## Status

Accepted

## Date

2026-08-24

## Context

Registry source tĩnh và `CustomSourceProfile` hiện tại không đáp ứng trải nghiệm no-code mà owner đã
chốt: dán listing URL, chọn seniority, xem preview 3–5 job, sửa mapping trực quan rồi crawl ngay hoặc
lên lịch. Việc bắt người dùng không chuyên tự viết adapter/selector cũng không phải product boundary
mong muốn.

Điều khoản website và rào cản truy cập là hai loại tín hiệu khác nhau. Một terms review có thể cảnh
báo operator về rủi ro và yêu cầu xác nhận rõ ràng, nhưng CAPTCHA, authentication, paywall, anti-bot,
HTTP access denial, SSRF hoặc redirect escape là technical control phải tiếp tục fail-closed.

## Decision

Thay runtime VNG, MoMo, NAVER/Greenhouse, RemoteJobs.org và `CustomSourceProfile` bằng một
`SourceRecipe` generic duy nhất:

- feature chỉ hợp lệ cho `LOCALHOST_SERVICE`, single operator và mặc định tắt;
- owner nhập HTTPS listing URL một lần vào persisted recipe; CrawlRun không nhận URL/header/cookie,
  proxy, selector hoặc code override;
- `restricted_terms` và `not_reviewed` luôn hiển thị notice, evidence, review date/version; owner có
  thể xác nhận đúng version để tiếp tục bounded preview/crawl;
- acknowledgement chỉ ghi nhận quyết định của operator, không phải permission hoặc legal
  certification và không che nội dung cảnh báo;
- CAPTCHA, authentication, paywall, anti-bot/challenge, `401/402/403`, access denial, private/reserved
  network target, DNS/redirect escape và unsupported credential flow là hard stop, không có bypass;
- extraction dùng structured data/HTTP deterministic trước và Playwright isolated fallback sau;
- preview 3–5 job hợp lệ là gate bắt buộc trước `enabled`; visual mapping chỉ trao đổi opaque element
  IDs, không lộ selector/code;
- enabled recipe sở hữu một `Source` có `approval_status=owner_authorized_local`; nó không trở thành
  global `approved`;
- schedule chỉ gồm manual, mỗi 6 giờ, daily và weekly trên PostgreSQL queue hiện có;
- hard cut xóa toàn bộ source-derived graph và adapter runtime cũ trong một migration transaction,
  không backup theo quyết định rõ ràng của owner và không release dual-run state;
- auth user/session, `ResumeProfile` và standalone `AlertRule` được giữ; source-linked `JobMatch` và
  `AlertDelivery` bị purge cùng source graph.

ADR-004 bị supersede đối với runtime owner-local hiện hành; lịch sử allow-list vẫn còn giá trị cho
evidence cũ. ADR-024 bị supersede toàn phần bởi `SourceRecipe`. Thiết kế chi tiết nằm tại
[No-code Source Recipes design](../superpowers/specs/2026-08-24-no-code-source-recipes-design.md).

## Alternatives considered

### Giữ adapter riêng cho từng website

- Ưu: parser ổn định hơn cho từng layout đã biết.
- Nhược: không đáp ứng URL mới nếu người dùng không code, tăng maintenance theo số nguồn.
- Không chọn cho product hiện hành.

### Arbitrary fetch/browser proxy có credential hoặc bypass

- Ưu: có thể truy cập nhiều luồng hơn.
- Nhược: tạo SSRF/credential exfiltration/abuse boundary và vượt technical access controls.
- Bị loại.

### LLM tự sinh selector hoặc điều khiển browser

- Ưu: có thể thích nghi layout nhanh.
- Nhược: HTML là untrusted input, output không deterministic và không được phép thay đổi route/tool
  policy.
- Bị loại; deterministic mapping đủ cho requirement hiện tại.

## Consequences

- Migration reset là irreversible đối với source-derived data; downgrade chỉ gỡ schema mới và không
  thể khôi phục hàng đã purge.
- Generic engine không cam kết mọi URL đều crawl được. Layout không đủ ba job, login/challenge hoặc
  interaction không hỗ trợ sẽ trả blocked/failure an toàn.
- Source terms có thể thay đổi; catalog notice cần version/evidence/review date và operator phải xác
  nhận lại khi version đổi.
- Feature không được bật trong protected/public deployment nếu chưa có ADR và boundary mới.
