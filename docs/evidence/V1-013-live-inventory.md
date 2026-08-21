# V1-013 — Live inventory và V1 exit blocker

**Ngày kiểm chứng:** 2026-08-21

**Scope:** full local non-commercial ingestion của ba approved source, parser regression, replay và V1 dataset exit gate

**Kết quả:** `blocked`

## 1. Full inventory

Ba source đã chạy tuần tự theo policy, không tăng concurrency:

| Source | Latest adapter version | Complete found | Canonical jobs |
|---|---|---:|---:|
| NAVER Vietnam/Greenhouse | `greenhouse-job-board-v1` | 14 | 14 |
| VNG Careers | `vng-careers-v2` | 27 | 27 |
| MoMo Careers | `momo-careers-v2` | 37 | 37 |
| **Tổng** | — | **78** | **78** |

PostgreSQL xác nhận `78` jobs, `78` distinct `(source_id, external_id)`, `78` distinct `(source_id, canonical_url)` và `78` distinct current snapshots. `/api/v1/jobs?pageSize=1` trả `pagination.totalItems=78`; `/api/v1/sources` trả đúng ba approved source và `lastSuccessAt` từ complete run.

Latest current-version runs đều `succeeded + complete`:

```text
NAVER: found=14 new=0 updated=0 failed=0 missing=0 removed=0
VNG v2: found=27 new=0 updated=0 failed=0 missing=0 removed=0
MoMo v2: found=37 new=0 updated=0 failed=0 missing=0 removed=0
```

Các full replay tạo raw snapshots mới có provenance nhưng không tạo thêm Job hoặc canonical update giả.

## 2. Live regression được phát hiện và sửa

Full VNG run đầu phát hiện 27 listings nhưng fail toàn bộ với `invalid_canonical_job`. Run được finalize `failed + incomplete`, giữ raw snapshots, ghi safe public error và để `items_missing/items_removed=0`; existing NAVER jobs không bị ảnh hưởng.

Root cause: VNG/MoMo ghép nhiều plaintext section bằng blank line, trong khi canonical upsert áp `normalize_text`; parser gán pre-normalized value vào `description_text`, tạo normalization mismatch. Fix nhỏ nhất nằm tại shared `redact_contacts`: redaction output được canonical text-normalize một lần trước khi cả `raw.description` và `normalized_candidates.description_text` dùng chung. Regression assertions khóa equality cho VNG/MoMo fixtures; parser version bump thành `vng-careers-v2` và `momo-careers-v2` để provenance phản ánh thay đổi output.

Sau fix, VNG full run tạo 27 jobs và MoMo full run tạo 37 jobs, đều 0 failure. Full `v2` replay tiếp theo trả 27/27 và 37/37 `unchanged`, chứng minh idempotency trên current parser version.

## 3. Verification

```text
python -m pytest
103 passed, 7 skipped

DEVRADAR_TEST_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:55432/postgres
python -m pytest
110 passed

python -m ruff check .
All checks passed!

python -m ruff format --check .
87 files already formatted

python -m mypy
Success: no issues found in 48 source files

python -m pip check
No broken requirements found.

docker compose --env-file .env.example --profile crawler config --quiet
exit 0
```

API image được rebuild/recreate sau fix và đạt health. Markdown local links, Git diff whitespace và task-board ignore checks cũng pass.

## 4. Blocker và điều kiện mở khóa

V1 yêu cầu tối thiểu 500 canonical jobs thật. Inventory approved hiện có `78/500`, thiếu `422`; criterion không đạt.

Không được:

- nhân bản, dùng fixture hoặc cross-source candidate để làm tăng count;
- crawl GeoComply/Lever khi record còn `permission_required`;
- thêm arbitrary source/URL ngoài registry;
- tự hạ gate hoặc chuyển V1/V2 status khi chưa có product decision.

V1 chỉ được mở khóa bằng một trong hai hướng:

1. approve thêm source qua policy/technical gate với inventory đủ lớn, rồi implement adapter và ingest; hoặc
2. product owner sửa exit criterion bằng rationale rõ, cập nhật roadmap/task contract trước khi đánh dấu complete.

Cho đến khi đó V1 giữ `blocked`, V2 giữ `proposed` và repository không được push theo yêu cầu “chỉ push khi xong phase”.

## 5. Resolution

Sau evidence này, product owner chọn thay fixed count bằng approved-inventory completeness/identity/replay gate. Quyết định và mapping toàn bộ exit criteria được ghi tại [V1 closeout](V1-closeout.md). Lịch sử `78/500` ở trên được giữ nguyên để thể hiện vì sao gate được xem xét lại; nó không còn là trạng thái phase hiện hành.
