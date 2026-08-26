# V6-023 — SourceRecipe identity và transactional graph purge

## Scope

Task bổ sung một identity ổn định cho mỗi SourceRecipe, hiển thị cùng contract trên API/dashboard và
tách hai lifecycle action:

- DELETE /api/v1/source-recipes/{recipeId} chỉ chuyển recipe sang retired, giữ audit/data;
- POST /api/v1/source-recipes/{recipeId}/purge xóa vĩnh viễn graph do đúng recipe sở hữu sau typed
  confirmation.

Task không thêm dependency, không mở arbitrary delete surface, không đổi local-only/no-bypass boundary và
không đóng các V6 provider/public gates còn mở.

## Contract đã kiểm chứng

- recipeCode = RCP- + 8 ký tự UUID hex đầu viết hoa; code là identifier hiển thị, không phải secret.
- lastUsedAt chỉ cập nhật khi preview, manual/scheduled run hoặc document import được chấp nhận.
- Dashboard hỗ trợ deep selection bằng query bounded
  /sources?recipeId={uuid}&view=active|collector|retired|all.
- Purge yêu cầu owner match, exact uppercase code, recipe retired và không có preview/CrawlRun
  pending|running.
- Missing/cross-owner dùng generic 404; wrong lifecycle/active dùng 409; invalid code dùng 422.
- Purge chạy trong một transaction, không backup/undo, với delete order explicit cho:
  AlertDelivery, JobMatch, JobEmbedding, ExtractionResult, JobChange, Job,
  RawJobSnapshot, retry graph CrawlRun, SourceRecipePreview, SourceRecipe, Source.
- ResumeProfile, AlertRule và graph source/owner khác được giữ nguyên.

## TDD và PostgreSQL evidence

RED coverage đầy đủ phát hiện purge cũ đặt retry_of_run_id = NULL, vi phạm
ck_crawl_runs_retry_relation. Fix xóa retry graph theo thứ tự leaf → parent, không nới constraint hoặc
ghi trạng thái trung gian invalid.

Targeted PostgreSQL:

    tests/integration/test_source_recipe_purge.py
    5 passed

Các case gồm full graph + exact deleted counts, unrelated graph retention, ResumeProfile/AlertRule
retention, wrong owner/state/code, active preview/run guard, second purge generic not-found, injected
source-delete rollback và concurrent two-session purge (1 success + 1 safe not-found).

Migration e8f2a4c6d901:

    upgrade c5d7e9f1a3b2 → e8f2a4c6d901
    downgrade e8f2a4c6d901 → c5d7e9f1a3b2
    upgrade c5d7e9f1a3b2 → e8f2a4c6d901
    nullable timestamptz last_used_at present only at head
    2 targeted schema tests passed

## Full quality gates

    default pytest: 386 passed, 95 skipped
    PostgreSQL pytest: 481 passed
    Ruff check: pass
    Ruff format --check: pass
    mypy: pass (149 source files)
    pip check: no broken requirements
    web: 82 tests passed; ESLint, TypeScript và Next.js production build pass
    Compose: api/web/crawler images built; migration applied; database/api/web/crawler healthy
    API health: status=ok
    web_smoke=pass base_url=http://127.0.0.1:3000
    secret scan: pass
    npm audit: 0 vulnerabilities
    supply-chain: pass; API/crawler/web fixable HIGH/CRITICAL = 0

Supply-chain lần đầu phát hiện ba finding OpenSSL cùng CVE-2026-14456 trong cached Debian layer
(3.5.6, fixed 3.5.7). No-cache rebuild chạy lại apt update/dist-upgrade cho API/crawler; scan lại xác nhận
API 18/0 fixable, crawler 33/0 fixable và web 31/0 fixable. Sau đó bốn Compose services được force-recreate
healthy và API/web smoke pass.

## Disposable API acceptance

Acceptance dùng hostname .example.test, document JSON local trong artifact ignored và không outbound
fetch. Flow:

    create → acknowledge current notice → import 3 jobs → replay bằng idempotency key mới
    → retire → exact-code purge

Kết quả:

    first import:  3 found / 3 new / 0 failed / incomplete
    second import: 3 found / 0 new / 3 unchanged / incomplete
    purge: 1 recipe / 1 source / 2 runs / 6 snapshots / 3 jobs / 3 changes
    post-purge target graph: absent
    TopCV jobs before/after: 3 → 3

## Browser verification

Dashboard thật được kiểm trên Compose build mới với một recipe retired disposable:

| Width | Document overflow | Selected-row overlap | Filter target |
|---:|---:|---:|---:|
| 375 | 0 | 0 | 44px |
| 768 | 0 | 0 | 44px |
| 1024 | 0 | 0 | 44px |
| 1440 | 0 | 0 | 44px |

Purge dialog ở 375px có aria-labelledby, aria-describedby, visible label chứa exact recipe code, input
nhận focus, action ≥44px và không overflow. Browser RED phát hiện Escape chưa đóng modal; component thêm
explicit onKeyDown fallback. GREEN xác nhận Escape đóng dialog và focus trở lại
Delete permanently. Recipe disposable được purge qua API sau phép kiểm tra.

## Remaining boundary

- Capability được chứng minh cho localhost/protected Compose; không phải public HTTPS deployment evidence.
- Purge cố ý không hỗ trợ undo/backup. Operator phải dùng retire nếu chỉ muốn ngừng sử dụng.
- Browser matrix kiểm Chromium engine hiện hành; Safari/Firefox không thuộc supported dashboard matrix.
