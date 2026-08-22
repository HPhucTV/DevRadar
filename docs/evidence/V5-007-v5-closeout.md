# V5-007 — Browser E2E, accessibility baseline và V5 closeout

## Trạng thái

`complete`. V5 giữ exposure `local/protected`; authentication, public ingress,
rate limiting và production notification secrets chuyển sang V6.

## UI slice

- Thêm route `/alerts` và navigation manifest `alerts`.
- Alert UI giữ owner token trong React memory, dùng same-origin BFF tới
  `AlertRule` CRUD/dispatch; không có webhook URL, cookie, localStorage hay raw
  CV/JD trong client.
- BFF có route cho list/create/patch/delete/dispatch và giữ `204 No Content`.
- Form có label/native controls, focus-visible style, live status/error region,
  responsive layout và protected-by-default copy.

## Browser verification

Native Python Playwright smoke: `output/playwright/v5_007_smoke.py`.

```text
overview / jobs / analytics / crawler-health   real API render pass
/jobs                                          3339 jobs in current result
/cv-match                                     protected default + invalid-token state pass
/alerts                                       owner form, mocked BFF CRUD/dispatch, pause state pass
accessibility baseline                         one h1, labelled inputs, named buttons on all routes
screenshots                                    v5_007-jobs-3339.png, v5_007-alerts.png
```

Alert browser actions use a bounded Playwright BFF stub so no real Discord
webhook/secret is used. Backend dispatch behavior is covered separately by
V5-006 PostgreSQL integration with a fake connector and real `AlertDelivery`
rows. CV full upload → match → delete browser smoke remains in
[V5-005 evidence](V5-005-cv-matching-ui.md), including `3339` considered jobs,
top 100 current matches and `204` deletion.

## Full V5 evidence map

- Dashboard/data: V5-001/V5-002 and browser smoke above;
- secure CV parser/lifecycle: V5-003;
- scoring/generation/API: V5-004;
- protected CV UI/delete: V5-005;
- alert connector/retry/idempotency: V5-006;
- web `npm run check` (5 tests, lint, typecheck, production build) and
  `npm audit --audit-level=high`: pass / 0 vulnerabilities;
- Python default suite: `231 passed, 53 skipped`;
- Python PostgreSQL suite: `284 passed`;
- Ruff, format, mypy, pip check, Compose config/build/migration/health: pass;
- Markdown local-link scan: pass.

## Exit-criteria boundary

Dataset evidence uses `3339` canonical jobs, above the `>=1000` gate. Dashboard
shows cohort/sample coverage; alert replay is idempotent; CV files/raw text are
validated/removed and absent from logs/responses. No public auth or external
secret claim is made before V6.
