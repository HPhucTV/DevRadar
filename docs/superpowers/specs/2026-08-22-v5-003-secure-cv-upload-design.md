# V5-003 Secure CV upload và ResumeProfile lifecycle — Design Spec

**Ngày:** 2026-08-22

**Trạng thái:** Đã được user ủy quyền quyết định và xác nhận tiếp tục
**Phase:** V5 — Dashboard, CV matching và alerts

## Mục tiêu

Cho phép portfolio operator upload một CV local/protected, validate file tại trust boundary, trích xuất profile deterministic và xóa file gốc mặc định. API chỉ hoạt động khi local gate bật; V6 sẽ thay owner-token gate bằng authn/authz chính thức.

## Threat model và assets

| Boundary | Abuse case | Control |
|---|---|---|
| Multipart request → app | file quá lớn, MIME giả, PDF/DOCX polyglot, zip bomb, path traversal | file cap `5 MiB`, total stream cap `5 MiB + 64 KiB` multipart framing, allow-list MIME/extension, magic bytes, bounded parser, reject unsafe ZIP entries |
| File parser → profile | malformed PDF/XML, embedded instruction/prompt injection, parser CPU/memory exhaustion | pypdf page/decode/text caps, DOCX allow-list `word/document.xml`, XML text only, no macros/external relationships; hard CPU timeout/process sandbox vẫn là boundary local |
| Owner header → resource | owner enumeration/cross-owner access | local gate, min/max opaque token, SHA-256 owner hash, every GET/DELETE owner match, no token in logs/response |
| Profile → database/API | PII/raw CV disclosure, stale data | persist hash + structured fields only, 24h expiry, sanitized response, delete endpoint |

Asset policy: raw CV file and raw text are ephemeral; `ResumeProfile` contains parser version, content hash, source format, bounded skills/role/location/experience and expiry. No external LLM, embedding or JobMatch is called in V5-003.

## API contract

- `POST /api/v1/resume-profiles` — `multipart/form-data`, exactly one `file`; requires `X-DevRadar-Owner`; default-disabled `DEVRADAR_CV_LOCAL_ENABLED=true` gate.
- `GET /api/v1/resume-profiles/{profileId}` — same owner header; returns sanitized structured profile.
- `DELETE /api/v1/resume-profiles/{profileId}` — same owner header; idempotent for an owned profile, returns `204`.
- Invalid/missing owner gate → `403`; unsupported MIME/signature/size/resource → `422` or `413`; unknown/other-owner resource → `404`.
- API never accepts a URL, raw text, parser option or provider selection.

Owner token is an operator-local secret supplied outside the request body. It is hashed with SHA-256 before persistence; raw token never enters logs, exception, database or response. This is a temporary protected-local boundary, not authentication.

## Parsing contract

- Accepted formats: PDF (`application/pdf`, `.pdf`, `%PDF-`) and DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `.docx`, ZIP signature `PK` plus `word/document.xml`).
- Max upload `5 MiB` và max total request `5 MiB + 64 KiB`; max extracted text `100,000` characters; max PDF pages `10`; max decoded PDF content stream/array `10 MiB` per page; max DOCX entries `100` and uncompressed member bytes `20 MiB`.
- DOCX parser reads only `word/document.xml`, strips XML tags via stdlib XML parser, rejects external relationship targets and macros/unsupported document structure.
- PDF parser uses `pypdf` page iteration and `extract_text`; no file is written to persistent storage. Empty/garbled text is `needs_review`/reject, never an accepted empty profile.
- Deterministic profile extraction uses current taxonomy aliases, bounded regex for years/role/location and parser version `resume-profile-parser-v1`. Unknown skills are omitted; no LLM fallback.

## Domain and lifecycle

`ResumeProfile` identity is UUID. Logical uniqueness is `owner_hash + content_hash + parser_version` for replay idempotency. Lifecycle:

```text
uploaded → active → expired
                  ↘ deleted
```

`expires_at = created_at + 24h`. A new upload with same owner/content/parser returns the existing active profile without storing another row. Delete is a soft tombstone (`deleted_at`) so the owner boundary and audit can be verified without retaining raw content; API treats deleted/expired rows as `404`.

## Alternatives

### Store the original file for later matching

Rejected: larger malware/PII/retention surface and violates default ephemeral CV policy.

### Send raw CV to DeepSeek for extraction

Rejected: ADR-008 synthetic-only and privacy boundary disallows CV/source content. Deterministic extraction is sufficient for V5-003 baseline.

### Add a separate upload service/queue

Rejected: one local portfolio consumer, no measured throughput need. Bounded in-process parsing plus DB transaction is the smallest complete boundary.

## Definition of Done

- Migration, model, parser and API have TDD fixtures for valid PDF/DOCX, wrong MIME/signature, oversize, zip bomb/path traversal, malformed parser, owner mismatch, expiry and delete.
- Default gate is fail-closed; raw file/text/token absent from logs, DB response and `ResumeProfile` API.
- PostgreSQL integration proves constraints, idempotent replay, owner isolation, expiry and deletion.
- Default/PostgreSQL/static/security/Markdown gates pass; no public auth claim.
