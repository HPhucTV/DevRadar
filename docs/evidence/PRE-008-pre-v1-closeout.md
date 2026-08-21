# PRE-008 — Pre-V1 closeout evidence

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Phase transition:** `pre_v1: complete` → `v1: in_progress`

## 1. Source gate

| V1 source | Approval | Identity | Completeness boundary | Fixture/live-smoke boundary |
|---|---|---|---|---|
| [VNG Careers](../sources/vng-careers.md) | `approved_local_noncommercial_spike` | `(source_id, job_id)` | numbered pages, stable `total/pages`, unique count bằng `total` | HTTP fixtures; tối đa hai list page và một detail trong bounded smoke |
| [NAVER Vietnam/Greenhouse](../sources/naver-vietnam-greenhouse.md) | `approved_local_noncommercial_spike` | `(source_id, public job post id)` | một JSON response, `jobs.length == meta.total` | JSON fixtures; một list và optional một detail, không gọi application/Harvest |
| [MoMo Careers](../sources/momo-careers.md) | `approved_local_noncommercial_spike` | `(source_id, jobId)` | fixed IT group, SSR batch đầu, public `Xem thêm` tới `TotalItems` | SSR/DOM/detail fixtures; một filtered navigation, một load-more và một detail trong bounded smoke |

GeoComply/Lever không được tính vào `3/3`: [record](../sources/geocomply-lever.md) giữ `approval_status=candidate` và `policy_status=permission_required` vì employer terms cấm automated retrieval. Chỉ written permission hoặc policy evidence mới được mở lại gate.

Approval của ba source V1 chỉ áp dụng cho local non-commercial spike/on-demand ingestion. Nó không cấp quyền public full-JD, scheduled/public crawling, commercial reuse, external LLM hoặc AI training.

## 2. MoMo bounded browser spike

- `GET /jobs-opening`: HTTP 200, SSR báo `TotalItems=107`, `PageCount=9`, 12 item đầu.
- `GET /jobs-opening?groups=DGM.0001`: HTTP 200, SSR báo 37 job thuộc `Trung tâm Công nghệ Thông tin`, 4 batch, 12 item đầu.
- Một click `Xem thêm` bằng public browser UI tăng số job link từ 12 lên 24.
- Sample detail HTTP 200 và giữ `jobId=17404`, `jobCode=26-T&H_ITC-0260`.
- Query `?page=2`/`?pageIndex=2` không đổi batch; adapter vì vậy không được giả định HTTP pagination.
- Frontend dùng request control cho API nền. Spike không tái tạo `X-Client-*` token; approval record cấm direct API replay và chỉ cho browser đi theo public UI.

Đây là shape/interaction evidence, không phải full crawl. Mọi load-more/control failure phải làm run `incomplete`, không được suy ra absence/removal.

## 3. Documentation và repository gates

| Gate | Evidence | Kết quả |
|---|---|---|
| Internal Markdown links/anchors | local checker chạy trên toàn bộ Markdown sau khi source/closeout records được tạo | Pass |
| Phase/source terminology | targeted `rg` không còn claim `0/3`, `2/3`, `hold_policy_unclear` hoặc Pre-V1 đang active | Pass |
| Domain/API/AI consistency | V1 `itemsMissing/itemsRemoved` bằng `0`; AI output dùng field `levels` cùng domain/API | Pass |
| Whitespace | `git diff --check` | Pass |
| Original idea preservation | không có diff cho `DevRadar_Agentic_Job_Market_Intelligence.md` | Pass |
| Local task board | `.gitignore` match `/TASK_BOARD.md`; file không tracked | Pass |
| Local prerequisites | [PRE-007 evidence](PRE-007-local-prerequisites.md) | Pass với port/runtime constraints đã ghi |
| Runnable app claim | README/AGENTS vẫn ghi chưa có scaffold hoặc verified Quick Start | Pass |

Không có application test/build để chạy ở Pre-V1. Docker/PostgreSQL capability evidence chỉ xác nhận môi trường local, không phải runtime proof của DevRadar.

## 4. Exit decision

Pre-V1 đạt exit criteria:

- baseline docs và bốn ADR nền tảng tồn tại;
- ba source thật có operator approval record, stable identity, completeness invariant, fixture plan và bounded smoke boundary;
- source có terms cấm automated retrieval không được đưa vào V1;
- local V1 prerequisites và port conflict đã được ghi;
- V1 task breakdown có dependency/DoD và `V1-001` đủ điều kiện chuyển `Ready`.

Roadmap được chuyển sang V1 `in_progress`. Việc scaffold, dependency lock và Quick Start chỉ được ghi khi `V1-001` thực sự chạy và được kiểm chứng.
