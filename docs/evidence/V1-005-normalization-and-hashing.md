# V1-005 — Normalization và canonical hashing

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** deterministic text/URL/location/salary/level/experience/skill-mention normalization và versioned canonical Job hash. Không gồm source parser, taxonomy/alias graph, Job upsert hoặc change event.

## 1. Normalization contract

Mỗi function trả `NormalizedValue` gồm exact `raw`, typed `value` và stable warning code. `null`/blank không được đổi thành giá trị giả.

| Nhóm | Hành vi V1 |
|---|---|
| Text | Unicode NFC, bỏ zero-width formatting chars đã khóa, collapse whitespace deterministic; raw giữ nguyên. |
| URL | Resolve relative URL, chỉ HTTPS/approved host/no user-info/no custom port; bỏ fragment; giữ query order và chỉ xóa parameter nằm trong explicit allow-list của caller. |
| Location | Chỉ map explicit HCM/Hanoi/Da Nang evidence; `Vietnam` không suy ra city; nhiều city hoặc work mode mâu thuẫn tạo warning. |
| Salary | Parse decimal/range, multiplier, explicit currency/period; không currency conversion; ký hiệu `$` thiếu code bị reject; range đảo không tự sort. |
| Level | Chỉ nhận token explicit `intern/fresher/junior/mid/senior/lead/manager`; số năm không sinh level. |
| Experience | Chỉ parse khi có unit year/năm; level text không sinh số năm; range đảo bị reject. |
| Skill mention | Chỉ Unicode/whitespace cleanup từng raw mention; không alias merge/taxonomy/classification trước V3. |

## 2. Canonical Job hash

`job-content-v1` serialize JSON UTF-8 với key order và decimal representation deterministic, rồi SHA-256. Payload gồm:

- canonical source URL;
- title, company, description;
- location raw + city/province/work mode;
- salary raw + min/max/currency/period;
- level raw + canonical ordered levels;
- experience min/max.

Fetch timestamp, run ID, selector metadata và warning không thuộc hash. Whitespace hoặc decimal scale (`50000000` so với `50000000.0000`) không đổi hash; salary/content có nghĩa đổi thì hash đổi. Skill chưa thuộc V1 canonical Job persistence nên không được âm thầm đưa vào hash; V3 taxonomy phải version hash/reprocessing plan nếu thêm.

## 3. Fixture evidence

[Fixture dataset](../../tests/fixtures/normalization_cases.json) có Việt/Anh, Unicode/NBSP/zero-width, relative URL, query preservation, explicit tracking removal, location ambiguous, remote/hybrid, VND/USD/no-currency, negotiable/reversed salary, mixed levels, years-only input và raw skill mentions.

Negative cases bắt buộc:

- host ngoài allow-list hoặc URL có user-info bị reject;
- `Vietnam` giữ city/province `null`;
- `Hanoi / HCMC` tạo `ambiguous_location` thay vì chọn ngẫu nhiên;
- `$1000/month` không tự nhận USD;
- `5000 - 3000 USD/month` tạo `salary_range_reversed`;
- `5 years of experience` không sinh level;
- `Senior level` không sinh experience.

## 4. Verification

| Gate | Kết quả |
|---|---|
| Normalization/hash fixture tests | `24 passed` |
| Full suite với PostgreSQL opt-in | `37 passed`, không warning |
| Ruff check/format | Pass |
| mypy strict | Pass, 20 source/test files |
| `pip check` / Alembic drift | Pass / no drift |
| Internal Markdown links | Pass |

Không thêm dependency, migration hoặc outbound request.

## 5. Boundary còn mở

- Adapter-specific extraction/HTML decoding dùng các function này từ `V1-006`–`V1-008`.
- `V1-009` chịu trách nhiệm đưa hash vào idempotent transaction/upsert.
- Location alias V1 cố ý nhỏ; alias mới cần fixture/evidence, không gọi geocoder ngầm.
- Skill taxonomy/alias, requirement type và skill persistence vẫn thuộc V3.
