# V6-011 GitHub Incident Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route unsuccessful `main` CI runs and an explicit drill into owner-assigned GitHub issues without adding a provider secret.

**Architecture:** A standalone least-privilege GitHub Actions workflow consumes only scalar
`workflow_run` metadata or manual dispatch metadata and invokes the preinstalled GitHub CLI. A static
Python contract test protects the trigger, permission and no-untrusted-code invariants; the real GitHub
dispatch/issue lifecycle is the integration gate.

**Tech Stack:** GitHub Actions, GitHub CLI, repository `GITHUB_TOKEN`, pytest, Markdown evidence

---

### Task 1: Add the workflow contract test

**Files:**

- Create: `tests/test_ci_incident_workflow.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path


WORKFLOW = Path(".github/workflows/incident-alert.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_incident_workflow_has_bounded_triggers_and_permissions() -> None:
    text = _workflow_text()

    assert "workflow_run:" in text
    assert "workflows: [\"DevRadar CI\"]" in text
    assert "branches: [main]" in text
    assert "types: [completed]" in text
    assert "workflow_dispatch:" in text
    assert "contents: read" in text
    assert "issues: write" in text
    assert "actions/checkout" not in text
    assert "download-artifact" not in text


def test_incident_workflow_routes_only_safe_metadata() -> None:
    text = _workflow_text()

    for conclusion in ("failure", "cancelled", "timed_out", "action_required"):
        assert f"github.event.workflow_run.conclusion == '{conclusion}'" in text
    assert "github.event.workflow_run.event == 'push'" in text
    assert "gh issue create" in text
    assert '--assignee "$REPOSITORY_OWNER"' in text
    assert "RUN_URL" in text
    assert "HEAD_SHA" in text
    assert "secrets." not in text
```

- [ ] **Step 2: Run RED verification**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_ci_incident_workflow.py -q
```

Expected: two failures with `FileNotFoundError` for `.github/workflows/incident-alert.yml`.

- [ ] **Step 3: Commit the test only after the RED output is captured**

```powershell
git add tests/test_ci_incident_workflow.py
git commit -m "test: define CI incident routing contract"
```

### Task 2: Implement the least-privilege alert workflow

**Files:**

- Create: `.github/workflows/incident-alert.yml`
- Test: `tests/test_ci_incident_workflow.py`

- [ ] **Step 1: Add the minimal workflow**

```yaml
name: DevRadar incident alert

on:
  workflow_run:
    workflows: ["DevRadar CI"]
    branches: [main]
    types: [completed]
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  route-incident:
    name: Route CI incident to GitHub Issues
    if: >-
      github.event_name == 'workflow_dispatch' ||
      (github.event.workflow_run.event == 'push' &&
       (github.event.workflow_run.conclusion == 'failure' ||
        github.event.workflow_run.conclusion == 'cancelled' ||
        github.event.workflow_run.conclusion == 'timed_out' ||
        github.event.workflow_run.conclusion == 'action_required'))
    runs-on: ubuntu-latest
    steps:
      - name: Create owner-assigned incident issue
        env:
          GH_TOKEN: ${{ github.token }}
          REPOSITORY_OWNER: ${{ github.repository_owner }}
          EVENT_NAME: ${{ github.event_name }}
          RUN_ID: ${{ github.event.workflow_run.id || github.run_id }}
          RUN_NUMBER: ${{ github.event.workflow_run.run_number || github.run_number }}
          RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt || github.run_attempt }}
          RUN_URL: ${{ github.event.workflow_run.html_url || format('{0}/{1}/actions/runs/{2}', github.server_url, github.repository, github.run_id) }}
          HEAD_SHA: ${{ github.event.workflow_run.head_sha || github.sha }}
          CONCLUSION: ${{ github.event.workflow_run.conclusion || 'drill' }}
        run: |
          if [[ "$EVENT_NAME" == "workflow_dispatch" ]]; then
            prefix="[DRILL]"
            summary="Manual routing drill; no production incident occurred."
          else
            prefix="[INCIDENT]"
            summary="DevRadar CI did not complete successfully on main."
          fi

          title="$prefix DevRadar CI run $RUN_NUMBER attempt $RUN_ATTEMPT"
          body=$(printf '%s\n\n- Workflow run: %s\n- Run ID: `%s`\n- Conclusion: `%s`\n- Commit: `%s`\n- Trigger: `%s`\n\nFollow `docs/runbooks/incident-response.md`; do not paste secrets or raw data into this issue.\n' \
            "$summary" "$RUN_URL" "$RUN_ID" "$CONCLUSION" "$HEAD_SHA" "$EVENT_NAME")

          gh issue create \
            --repo "$GITHUB_REPOSITORY" \
            --title "$title" \
            --body "$body" \
            --assignee "$REPOSITORY_OWNER"
```

- [ ] **Step 2: Run GREEN and static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_ci_incident_workflow.py -q
.venv\Scripts\python -m ruff check tests/test_ci_incident_workflow.py
.venv\Scripts\python -m ruff format --check tests/test_ci_incident_workflow.py
```

Expected: `2 passed`; Ruff commands exit `0`.

- [ ] **Step 3: Inspect the workflow for the trust-boundary invariants**

```powershell
rg -n "checkout|download-artifact|secrets\.|issues: write|gh issue create|workflow_run" .github/workflows/incident-alert.yml
```

Expected: no checkout/download/`secrets.` match; bounded trigger, permission and create command present.

- [ ] **Step 4: Commit implementation**

```powershell
git add .github/workflows/incident-alert.yml
git commit -m "ci: route failed main runs to GitHub Issues"
```

### Task 3: Document and remotely drill the route

**Files:**

- Create: `docs/evidence/V6-011-github-incident-alerting.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/ROADMAP.md`
- Modify local ignored `TASK_BOARD.md`

- [ ] **Step 1: Add repository intent before remote evidence**

Create `docs/evidence/V6-011-github-incident-alerting.md` with this initial content, then add the exact
run/issue identifiers only after the remote drill:

```markdown
# V6-011 — GitHub incident alerting

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — local contract implemented; remote routing drill pending.

## Boundary

- Failed/cancelled/timed-out/action-required push CI on `main` creates an owner-assigned GitHub issue.
- Manual dispatch creates an explicit `[DRILL]` issue through the same route.
- Workflow grants only `contents: read` and `issues: write`, and never checks out code or reads artifacts.
- Issue payload contains only run URL/ID, conclusion, SHA and event; no logs, secrets or application data.

## Boundary còn mở

This route observes CI only. Public uptime, HTTPS ingress, managed application secrets and encrypted
off-host PostgreSQL backup remain V6 closeout gates.
```

Update `docs/OPERATIONS.md` with the trigger, least-privilege and incident-closure rule. Add V6-011 as
`In Progress` to the local ignored task board, and mention the bounded route under V6-005 progress in
`docs/ROADMAP.md` without changing V6-005/V6-007 status.

- [ ] **Step 2: Run broad local verification**

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
git diff --check
```

Expected: every command reaches a terminal success result.

- [ ] **Step 3: Commit and push**

```powershell
git add .github/workflows/incident-alert.yml tests/test_ci_incident_workflow.py docs/OPERATIONS.md docs/ROADMAP.md docs/evidence/V6-011-github-incident-alerting.md docs/superpowers/plans/2026-08-23-v6-011-github-incident-alerting.md
git commit -m "docs: record CI incident routing boundary"
git push origin main
```

Do not add `TASK_BOARD.md`.

- [ ] **Step 4: Wait for the exact pushed SHA CI run**

Authenticate API reads from `git credential fill` without printing the password. Select the `push` run
from `GET /repos/HPhucTV/DevRadar/actions/runs?branch=main&event=push` whose `head_sha` equals
`git rev-parse HEAD`, then poll that run and its jobs until `status=completed`. Require `conclusion=success`
and seven successful jobs. Do not treat a skipped alert job on successful CI as incident evidence.

- [ ] **Step 5: Dispatch and verify the real alert workflow**

Record UTC time, then call `POST /repos/HPhucTV/DevRadar/actions/workflows/incident-alert.yml/dispatches`
with JSON `{"ref":"main"}`. Select the first later `workflow_dispatch` run for that workflow, poll it to
`completed/success`, then query repository issues created after the recorded time. Require exactly one
matching open issue whose title begins `[DRILL]`, author is `github-actions[bot]`, assignee is `HPhucTV`,
and body contains only the alert run URL/ID, `drill`, SHA and runbook warning.

- [ ] **Step 6: Close the drill issue and record immutable evidence**

Call `POST /issues/{number}/comments` with `Routing drill verified; no production incident.` and
`PATCH /issues/{number}` with JSON `{"state":"closed","state_reason":"completed"}`. GET the issue again
and require `state=closed`, `state_reason=completed`. Record workflow run URL, issue URL/number, timestamps
and safe field assertions in the evidence file. Commit/push the evidence update, then wait for the exact
resulting CI SHA to finish.
