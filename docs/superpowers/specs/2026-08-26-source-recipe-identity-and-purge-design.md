# SourceRecipe Identity and Transactional Purge Design

## Status

Approved in principle by the product owner on 2026-08-26; written spec pending final owner review.

## Problem

Operator không biết recipe nào tương ứng với run đang vận hành vì:

- web list chỉ hiển thị raw name, origin và status;
- acceptance/test recipes trộn với recipe đang vận hành;
- một collection run không có signal `lastUsedAt` trên recipe;
- dashboard không có deep link chọn exact recipe.

Owner chọn mô hình: một recipe ổn định theo exact URL, mỗi lần dùng tạo run riêng. Owner cũng chọn hai hành
động tách biệt: **Ngừng sử dụng** giữ audit graph, còn **Xóa vĩnh viễn** purge toàn bộ graph trong database.

## Scope

### Tracked product scope

- PostgreSQL/Alembic `last_used_at` projection.
- Additive FastAPI/OpenAPI fields và purge command.
- Transactional purge service với owner/local/state/confirmation guards.
- Next.js SourceRecipe identity, filters, deep selection, retire và purge confirmation UI.
- Documentation, contract/integration/security/browser tests.

### Non-goals

- Không tạo recipe mới cho mỗi run.
- Không thêm multi-user sharing, Telegram hoặc cloud sync.
- Không xóa ResumeProfile/AlertRule không phụ thuộc source.
- Không backup, restore hay undo purge.
- Không cho purge arbitrary Source hoặc job qua public ID.
- Không thay đổi no-bypass/SSRF/credential boundary.

## Ubiquitous language

| Term | Definition |
|---|---|
| Recipe code | `RCP-` + tám hex đầu UUID, display/confirmation value, không phải secret. |
| Recipe label | Presentation label từ raw name/origin/seniority; không thay raw name/domain identity. |
| Recipe run | Một preview, canonical crawl hoặc document import gắn với stable recipe/source. |
| Last used | Thời điểm server chấp nhận preview/crawl/import cho recipe; không phải config update. |
| Retire / Ngừng sử dụng | Terminal lifecycle state, không tạo run mới, giữ toàn bộ audit graph. |
| Purge / Xóa vĩnh viễn | Irreversible physical deletion của recipe-derived source graph. |

## Identity contract

### Recipe code

Server helper và typed web contract phải cho cùng output:

```text
f1fe63e0-61dc-40b7-93c2-72c670c28155 → RCP-F1FE63E0
```

API không persist `recipe_code`; server response có thể trả computed `recipeCode` để loại duplicate client
logic. Confirmation body phải match exact uppercase code của owned recipe.

### Last-used projection

Migration thêm nullable timezone column:

```text
source_recipes.last_used_at TIMESTAMPTZ NULL
```

Update points:

- preview request accepted;
- manual/scheduled crawl request accepted;
- document import passes recipe/notice validation và bắt đầu canonical run.

Failed validation, config PATCH, terms acknowledgement, list/get và mapping submit không cập nhật
`last_used_at`. Existing rows giữ `null`, UI hiển thị “Chưa chạy”.

### Presentation and deep selection

Dashboard URL:

```text
/sources?recipeId={uuid}&view=active|collector|retired|all
```

- invalid UUID is ignored, not forwarded to backend;
- exact owned recipe is selected, highlighted, scrolled into view and history loaded;
- missing/cross-owner target shows generic safe state without leaking existence;
- collector group is presentation-only and may infer the existing `Collector ·` raw-name convention;
- custom/acceptance recipes remain visible through `all`, not deleted or silently hidden.

Each row reserves distinct columns for main identity, scope, last-used, lifecycle and action. At narrow
widths, action moves to a dedicated bottom/action row; it never overlays text.

## API contract

### Existing retire endpoint

```http
DELETE /api/v1/source-recipes/{recipeId}
→ 204 No Content
```

Meaning remains unchanged: recipe/source become `retired`.

### New purge command

```http
POST /api/v1/source-recipes/{recipeId}/purge
Content-Type: application/json

{"confirmationCode":"RCP-F1FE63E0"}
```

Success:

```json
{
  "data": {
    "recipeId": "f1fe63e0-61dc-40b7-93c2-72c670c28155",
    "sourceId": "38e9abb7-2cd2-4072-8784-130da0a442ac",
    "deleted": {
      "sourceRecipes": 1,
      "sourceRecipePreviews": 2,
      "sources": 1,
      "crawlRuns": 4,
      "rawJobSnapshots": 12,
      "jobs": 3,
      "jobChanges": 1,
      "extractionResults": 0,
      "jobEmbeddings": 0,
      "jobMatches": 0,
      "alertDeliveries": 0
    }
  }
}
```

Status/error mapping:

| Status | Code | Condition |
|---:|---|---|
| `401/403` | existing auth/CSRF codes | protected boundary failure |
| `404` | `source_recipe_not_found` | missing or cross-owner |
| `409` | `recipe_purge_requires_retired` | recipe chưa retired |
| `409` | `recipe_purge_active` | preview hoặc CrawlRun pending/running |
| `422` | `recipe_purge_confirmation_invalid` | code sai/schema sai |

Purge không idempotent trên resource đã biến mất: call thứ hai trả generic `404`. Response không chứa raw
content hoặc URL.

## Transactional delete graph

Service lấy row lock cho owned recipe và source. Nếu không có source, xóa previews + recipe. Nếu có source,
delete trong một transaction theo dependency order:

1. collect source job/run/snapshot IDs và impact counts;
2. reject pending/running preview/run;
3. delete `alert_deliveries` cho source jobs;
4. delete `job_matches`, `job_embeddings`, `extraction_results` cho source jobs;
5. delete `job_changes` cho source jobs/runs/snapshots;
6. delete source jobs (sau khi dependent rows ở step 3–5 đã biến mất); `current_snapshot_id` là non-nullable
   nên không tạo intermediate NULL state;
7. delete raw snapshots;
8. set `crawl_runs.retry_of_run_id = NULL` trong source cohort, rồi delete crawl runs;
9. delete source recipe previews;
10. delete source recipe;
11. delete source.

Transaction rollback giữ nguyên graph nếu bất kỳ step/count/assertion lỗi. ResumeProfile và AlertRule không
được chọn để delete; FK cascade liên quan jobs chỉ là defense-in-depth, service vẫn count/delete explicit
cho report ổn định.

## Web UX

### List and identity

- default view ưu tiên non-retired recipes, selected/deep-linked recipe luôn visible;
- row hiển thị recipe label, generic `Local Collector` badge khi phù hợp, recipe code, shortened URL,
  seniority scope, `lastUsedAt` và lifecycle status;
- acceptance/test recipes nằm trong `all`, không trộn vào default active collector focus;
- overflow menu có fixed action column; responsive layout không absolute-overlay action.

### Retire

“Ngừng sử dụng” mở non-destructive confirmation và gọi existing DELETE. Success cập nhật row `retired`,
không biến mất khỏi `retired/all`, không xóa jobs/history.

### Purge

“Xóa vĩnh viễn” chỉ enabled cho retired recipe. Dialog:

- liệt kê graph sẽ xóa và dữ liệu được giữ;
- yêu cầu nhập exact recipe code;
- confirm button disabled tới khi exact match;
- busy state không cho submit lặp;
- `409 active` hướng operator chờ/stop current work;
- success remove row, clear URL selection và announce deleted counts trong polite status;
- cancel/Escape giữ recipe và trả focus về action trigger.

## Security and abuse cases

- Cross-owner recipe ID: generic `404`, không count hoặc leak graph.
- Confirmation code của recipe khác: `422`, không delete.
- Double submit/concurrent purge: row lock; một success, request còn lại safe conflict/not-found.
- Pending/running work: `409`, không cancel/purge âm thầm.
- Crafted JSON/extra field/overlong code: `422` ở BFF và FastAPI boundary.
- Purge transaction failure: rollback, counts không được trả như success.
- Logs không chứa raw HTML/JD/CV, full listing query hoặc secrets.

## Testing and acceptance

### Backend

- pure recipe code tests;
- migration upgrade/downgrade and PostgreSQL schema check;
- unit/service tests cho empty recipe và full source graph;
- rollback injection tại giữa delete order;
- active/cross-owner/confirmation/double-purge negatives;
- OpenAPI and docs contract updates;
- integration verifies only target graph deleted; other source/ResumeProfile/AlertRule retained.

### Web

- VI/EN dictionary parity;
- query-param deep selection and invalid UUID behavior;
- action column never overlaps at `375/768/1024/1440`;
- retire retains row/data state;
- purge dialog keyboard/focus/typed confirmation/error/success;
- existing source policy/CSRF/no-bypass tests remain green.

## Rollout and evidence

1. Implement migration/API/service/docs behind existing localhost SourceRecipe gate.
2. Implement tracked web identity/actions and browser matrix.
3. Acceptance uses a disposable recipe/source graph; never purge current TopCV evidence recipe during test.
4. Push tracked backend/web/docs only after full gates.

## Alternatives rejected

- New recipe per run: increases clutter and breaks stable identity.
- Rename-only convention without recipe code/deep link: still ambiguous.
- Change existing DELETE to purge: backward-incompatible and unsafe.
- Purge recipe row only: violates “xóa trong DB” expectation and leaves graph.
- Automatic purge on retire: removes audit data without a distinct irreversible confirmation.
