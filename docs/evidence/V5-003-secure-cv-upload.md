# V5-003 — Secure CV upload và ResumeProfile lifecycle

**Status:** `complete` ngày 2026-08-23. Independent re-review xác nhận `0 Critical`, `0 Important`; final test/static/Markdown/security/Compose gates đều pass.

## Kết quả

- Ba endpoint `/api/v1/resume-profiles` được default-disable bằng `DEVRADAR_CV_LOCAL_ENABLED=false`; đây là local/protected gate, không phải authentication V6.
- `X-DevRadar-Owner` nhận opaque token 32–128 ký tự. Runtime chỉ persist SHA-256 và dùng owner predicate cho mọi read/delete; cross-owner trả generic `404`.
- Parser deterministic nhận đúng PDF/DOCX, kiểm extension + MIME + magic bytes và giới hạn file/page/archive/decoded text. DOCX từ chối path traversal, symlink, duplicate entry, macro/embedded object, external relationship, DTD/entity và malformed XML.
- Database chỉ giữ profile structured, content hash, owner hash cùng lifecycle metadata. File gốc và extracted raw text không có trong model, migration, response hoặc event.
- Replay cùng owner/content/parser còn hạn trả cùng resource; profile hết hạn được tombstone khi replay; delete cùng owner idempotent và GET của row deleted/expired trả `404`.
- Event `resume_profile_processed` chỉ giữ profile ID, source format, extraction status và `created|reused`.
- Local gate/owner chạy trước multipart read. Toàn request, kể cả chunked/no `Content-Length`, bị cap trước parse; OpenAPI vẫn mô tả multipart và owner header required trên cả ba operation.
- Pypdf decoder/array limits được hạ từ default khoảng 75 MB xuống `10 MiB + 1 byte`; `LimitReachedError` thành safe parser code. Toàn bộ `pypdf` diagnostics bị suppress vì malformed CMap có thể echo raw CV bytes.

## TDD và security regression

Parser/API/persistence tests được viết RED trước implementation theo plan. Trong closeout review, malformed multipart có hai file cho thấy file tạm thứ hai chưa được đóng:

```text
FAILED test_invalid_multipart_closes_every_uploaded_file
AssertionError: assert second.file.closed
```

Root cause là reject path chỉ gọi `file.close()` trên một `UploadFile` do FastAPI inject. Fix tại boundary gọi `FormData.close()` để đóng toàn bộ file part; regression sau fix:

```text
1 passed
Ruff: All checks passed!
mypy: Success: no issues found in 2 source files
```

Independent review tiếp tục tạo ba RED security/contract regressions:

```text
uncaught pypdf.errors.LimitReachedError trên compressed 75,000,001-byte stream
chunked request: read_resume_upload() chưa có pre-parse stream cap
default gate expected 403 nhưng FastAPI form parse chạy trước và trả 400
pypdf._cmap WARNING chứa sentinel raw bytes
OpenAPI owner header required=false
```

Fix giữ ở boundary chung: endpoint tự stream-cap rồi mới bounded multipart parse, pypdf decoder cap trước allocation lớn, package logger fail-silent, và explicit OpenAPI required header trong khi missing runtime header vẫn trả `403`.

## Verification đã chạy

| Gate | Kết quả |
|---|---|
| Default pytest | `202 passed, 39 skipped in 6.10s` |
| PostgreSQL full pytest | `241 passed in 52.91s` |
| Parser targeted trước security review | `17 passed in 2.21s` |
| Parser targeted sau review fixes | `19 passed in 2.78s` |
| Resume API/persistence targeted PostgreSQL | `15 passed in 10.70s` |
| Ruff check/format | `All checks passed!`; `189 files already formatted` |
| mypy strict | `Success: no issues found in 84 source files` |
| Next.js `npm run check` | route test, ESLint, TypeScript và production build pass; không có `/api` Route Handler |
| `npm audit --audit-level=high` | `found 0 vulnerabilities` |
| Python dependency integrity | `pip check`: `No broken requirements found` |
| Compose config | crawler profile `config --quiet` exit `0` |
| Docker API image | build exit `0`; `devradar-app:local Built` |
| Existing-volume migration | `a1d4e7f9b203 -> b3c7d9e2f401` applied transactionally |
| Default gate smoke | health `200`; ResumeProfile POST `403 cv_local_disabled` |
| Hardened gate-on HTTP smoke | PDF/DOCX/malformed-CMap `200`; oversized total request `413`; same-owner GET `200`, wrong-owner GET `404`, DELETE `204`, GET sau delete `404`; OpenAPI owner header required |
| Gate restoration | API recreated với `false`; health `200`, POST `403` |
| Secret-shaped token scan | `0` file trong tracked/untracked non-ignored scope |
| Markdown internal links | `94 files`, `225 links`, `0 invalid` |
| Final diff/ignored tracker | `git diff --check` pass; `TASK_BOARD.md` untracked và ignored |

Python vulnerability scanner `pip-audit` không có trong verified toolchain. Không thêm package chỉ để chạy một closeout scan; exact runtime pins/hashes được review, clean install và `pip check` vẫn là gate hiện hành. Web dependency audit có scanner được lock sẵn và trả `0 vulnerabilities`.

Independent review ban đầu phát hiện bốn Important issue: pre-gate multipart spooling, pypdf decode amplification/uncaught limit, raw pypdf diagnostic và optional OpenAPI owner header. Tất cả có RED fixture, boundary fix và targeted/full verification; re-review sau fix trả `0 Critical`, `0 Important`. Concurrency replay-vs-delete stress test chưa được thêm; PostgreSQL partial unique index + `ON CONFLICT DO NOTHING` hiện được integration-test tuần tự và sẽ được mở rộng khi có concurrent caller thực tế.

## Privacy và resource boundaries

- Không đọc/log `.env.local`, owner token, raw CV hoặc extracted text trong smoke/evidence. Synthetic PDF/DOCX chỉ tồn tại in-memory ở HTTP client.
- Parser chạy bounded nhưng vẫn ở cùng API process và ngoài database transaction. V5-003 chưa chứng minh OS-level process sandbox, hard memory/CPU limit hoặc antivirus/content-disarm; vì vậy endpoint tiếp tục default-disabled local/protected và chưa phù hợp public ingress.
- Application đã cap total request stream trước multipart parse, nhưng đây không thay thế ingress/proxy rate limit, connection timeout, concurrent-request budget hoặc OS-level CPU/memory enforcement của V6.
- Expired structured rows bị ẩn và được tombstone khi replay/delete, nhưng chưa có scheduled physical purge. Protected-demo cleanup và cascading delete cho future embedding/JobMatch thuộc V5-005/V5-007.
- Không có OCR, LLM, external provider, CV embedding hoặc JobMatch trong task này. CV không rời local runtime.
