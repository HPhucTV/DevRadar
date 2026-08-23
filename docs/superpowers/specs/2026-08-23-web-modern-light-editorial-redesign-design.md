# DevRadar Web Modern Light Editorial Redesign

## Trạng thái

`Approved for implementation` bởi product owner qua hội thoại ngày 2026-08-23.

## Design read

Redesign toàn bộ dashboard DevRadar cho single-operator và portfolio reviewer, dùng ngôn ngữ Modern Light SaaS
tin cậy, giàu dữ liệu, với typography editorial để sản phẩm có quan điểm riêng thay vì giống admin template.

## Quyết định thẩm mỹ

- `DESIGN_VARIANCE: 6`: bố cục có nhịp và phân cấp rõ, không đối xứng máy móc nhưng không làm khó thao tác.
- `MOTION_INTENSITY: 3`: chỉ dùng hover, focus, transition và feedback trạng thái ngắn; không thêm animation library.
- `VISUAL_DENSITY: 5`: đủ thông tin cho jobs/analytics/operations nhưng giữ khoảng thở ở các heading và empty state.
- Một light theme duy nhất trên toàn bộ app. Không tự chuyển dark theo hệ điều hành.
- Design system CSS-native hiện tại; không thêm UI framework, font package, icon package, chart package hay state library.

## Mục tiêu

1. Chuyển nền xanh lá tối/thô hiện tại sang nền light SaaS sáng, contrast tốt và có surface hierarchy.
2. Giữ nguyên route slug, navigation labels, API/BFF contracts, auth/privacy boundaries và các semantics an toàn.
3. Làm ba surface chính trong proposal thành baseline chung: overview dashboard, CV matching và jobs explorer.
4. Đưa cùng visual language tới analytics, crawler health, alerts, privacy và job detail.
5. Không tạo cảm giác hệ thống phóng đại insight: cohort, denominator, coverage và source provenance vẫn phải nhìn thấy.

## Không thuộc phạm vi

- Không đổi route, backend endpoint, schema, API response, auth/CSRF, owner authorization, upload/delete semantics hoặc polling.
- Không thêm chart renderer, icon dependency, external font, animation dependency hoặc client state toàn app.
- Không thay đổi copy pháp lý/privacy/consent.
- Không dựng score ring/progress bar mang hàm ý xác suất tuyển dụng; CV match dùng score tile, evidence coverage và matched/missing skills.
- Không thiết kế lại public marketing landing page vì frontend hiện là protected dashboard.

## Token và visual language

```css
--bg: #F6F8FC;
--surface: #FFFFFF;
--surface-subtle: #EEF2F8;
--text: #132039;
--muted: #69758B;
--line: #DFE6F1;
--accent: #4F46E5;
--accent-soft: #EEF2FF;
--cyan: #0891B2;
--success: #059669;
--success-soft: #ECFDF5;
--warning: #D97706;
--warning-soft: #FFFBEB;
--danger: #B42318;
--danger-soft: #FEF3F2;
```

- Panel radius: `12px`; outer featured surface may use `16px` only when it is a distinct composition.
- Badge/chip radius: `999px`.
- Border: one-pixel `--line`; avoid border on every row when spacing can provide grouping.
- Shadow: one soft elevation token for actionable/featured panels; avoid glassmorphism.
- Sans stack: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- Editorial heading stack: `Georgia, "Times New Roman", serif`, reserved for page title/insight headline only.
- Focus ring: visible Indigo ring with offset; keyboard navigation must remain obvious.

## Shared shell

`AppShell` receives no new data dependency. It keeps `routes.json` as navigation source and renders:

- one-line desktop header with small DevRadar mark, brand, primary nav and authenticated user control;
- responsive wrapping nav at narrow widths without changing links or route labels;
- consistent page width and vertical rhythm;
- privacy link in footer;
- no status color used without a text label.

The mark is CSS-native and decorative; accessible brand text remains visible. Auth controls keep the current
session behavior and do not expose session credentials.

## Route composition

### Overview `/`

- Editorial intro with one eyebrow, title and short explanation.
- Four Metric cards: visible jobs, approved sources, tracked skills, fresh jobs.
- Two-column content: skill demand visualization built from existing data and latest verified job feed.
- Mobile collapses metrics to two columns and content to one column.

### Jobs `/jobs`

- Filter bar keeps `query`, `location` and `page` names/values.
- Job card keeps title, source, date, company, location, salary raw text and levels.
- Source is a small verified badge, not a claim about employer endorsement.
- Pagination/result count remains visible.

### Job detail `/jobs/[jobId]`

- Two-column detail on desktop: primary description/provenance and metadata rail.
- Mobile stacks metadata below description.
- Raw salary and source link stay visible; no inferred salary/currency is added.

### Analytics `/analytics`

- Cohort, analyzed jobs, coverage and taxonomy remain first-order metrics.
- Skill list and trend buckets use different panel rhythm to avoid repetitive rows.
- Period context remains explicit and no chart claims exceed API denominator.

### CV Match `/cv-match`

- Existing file input is visually presented as a protected upload card without changing acceptance rules.
- Profile summary, TTL, extraction status and delete action remain visible.
- Generation metrics use existing values.
- Match card uses a score tile, evidence coverage, job metadata, matched/missing skill columns and source link.
- Original CV/raw text/privacy notices remain visible and unchanged semantically.

### Crawler Health `/crawler-health`

- Source registry becomes a health card/list with status text, reason code and approved-source action.
- Workflow history uses a compact timeline/list grouping; polling and terminal status behavior is untouched.
- Healthy/degraded/unknown states use color plus text.

### Alerts `/alerts`

- Rule builder is a featured panel with clear required filter hint.
- Owner rules become cards with bounded action grouping: dispatch, pause/enable, delete.
- Existing CSRF, owner session and replay-safe messaging remain unchanged.

### Privacy `/privacy`

- Policy sections receive editorial headings, compact callouts and readable retention groupings.
- Legal/source wording is preserved; visual hierarchy only.

## Responsive behavior

- Primary breakpoint: `700px`.
- Page container remains fluid with safe horizontal padding and `max-width`.
- Desktop grids collapse to one column where content is more important than density.
- Job metadata moves below title/company; action buttons become full-width or wrap without clipping.
- No horizontal scrolling on 320px viewport; file input and long URLs wrap safely.
- Use `min-height: 100dvh` where viewport-height composition is needed; never rely on fixed `h-screen`.

## Accessibility and interaction

- Preserve semantic headings, landmarks, labels, `aria-live` status and `role="alert"` states.
- Every focusable action has a visible focus ring and sufficient contrast.
- Status colors are paired with text; matched/missing skills are not color-only.
- Buttons retain disabled/busy feedback; no action silently disappears while requests run.
- Respect `prefers-reduced-motion`; all motion is optional and short.
- Verify keyboard traversal through header/nav, filters, upload, cards, alert controls and deletion actions.

## Error, empty and loading states

`ApiErrorState`, `EmptyState`, loading surfaces and status messages keep current safe text and error codes. Their
visual treatment is normalized with the new surface, border, accent and spacing tokens. No raw backend exception,
CV text, token, webhook or sensitive data is introduced into rendering.

## Implementation boundary

Expected code touch points:

- `web/src/app/globals.css`
- `web/src/components/app-shell.tsx`
- `web/src/components/api-state.tsx`
- `web/src/components/job-list.tsx`
- `web/src/components/cv-match-panel.tsx`
- `web/src/components/alert-rules-panel.tsx`
- `web/src/components/ingestion-console.tsx`
- affected route page files under `web/src/app/(dashboard)/`

No new dependency or API contract is expected. If implementation reveals a missing data field, stop and update the
contract/spec before inventing a visual placeholder.

## Verification plan

1. `npm run check` from `web/`.
2. Existing route contract tests remain green.
3. Run local app with backend fixtures and use browser smoke for login, overview, jobs/filter, job detail, analytics,
   CV upload/match/delete, alerts, crawler health and privacy.
4. Verify 1280px desktop and 320px mobile layouts; inspect overflow, focus, contrast and reduced-motion behavior.
5. Review diff to confirm no API, auth, privacy, route slug or source policy changes.

## Acceptance criteria

- All dashboard routes share the same light/editorial system and no route falls back to the old green palette.
- The three proposal surfaces visibly match Modern Light SaaS structure with editorial typography.
- Existing API/BFF and security flows pass without contract changes.
- No new dependency is added.
- `npm run check` and browser smoke pass.
- Empty, loading, error, disabled and mobile states remain usable and legible.
