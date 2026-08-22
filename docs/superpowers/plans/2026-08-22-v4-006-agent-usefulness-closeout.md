# V4-006 Agent Usefulness Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Loại runtime agent không chứng minh được measurable usefulness, giữ migration/decision history và đóng V4 bằng evidence trung thực.

**Architecture:** Deterministic V1–V3 workflows tiếp tục là production path. Một ADR mới supersede phần direct-agent runtime của ADR-012; một Alembic revision kế tiếp drop `agent_runs`; toàn bộ package/test chỉ phục vụ proposal workflow bị xóa thay vì giữ dead abstraction.

**Tech Stack:** Python 3.13, FastAPI modular monolith, SQLAlchemy 2, Alembic, PostgreSQL 18, pytest, Ruff, mypy, Docker Compose.

---

## File map

- Create `docs/decisions/0013-remove-unretained-v4-agent-runtime.md`: authoritative keep/delete decision và reconsideration gate.
- Modify `docs/decisions/README.md`: index ADR-013 và trạng thái ADR-012.
- Modify `tests/integration/test_postgresql_schema.py`: regression cho historical `agent_runs` revision và head schema không còn bảng.
- Create `migrations/versions/a1d4e7f9b203_remove_unretained_agent_runtime.py`: drop schema ở upgrade, tái tạo historical schema ở downgrade.
- Modify `migrations/env.py`: bỏ metadata import của model đã loại.
- Delete `src/devradar/agents/`: xóa runtime proposal/policy/run-state/persistence không có consumer.
- Delete `tests/test_agent_*.py` và `tests/integration/test_agent_*.py`: xóa test chỉ bảo vệ feature đã loại.
- Modify `README.md`, `AGENTS.md`, `docs/AI.md`, `docs/ARCHITECTURE.md`, `docs/DOMAIN_MODEL.md`, `docs/ROADMAP.md`: current-state docs không còn claim runtime agent/AgentRun active.
- Create `docs/evidence/V4-006-agent-usefulness-closeout.md`: comparison, removal, migration và verification evidence.
- Modify local ignored `TASK_BOARD.md`: V4-006 Done, V4 complete, V5-001 Ready.

### Task 1: Record the keep/delete decision

**Files:**

- Create: `docs/decisions/0013-remove-unretained-v4-agent-runtime.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: Add ADR-013**

Write an `Accepted` ADR with these exact decisions:

```markdown
# ADR-013: Loại V4 agent runtime không chứng minh measurable usefulness

## Status

Accepted — supersedes phần direct planner/validator/analyst runtime của ADR-012. ADR-012 vẫn giữ quyết định defer LangGraph.

## Date

2026-08-22

## Decision

- Loại cả ba reasoning path `planner`, `validator`, `analyst`.
- Giữ V1–V3 deterministic workflows làm authoritative production path.
- Xóa package `devradar.agents`, test riêng và bảng `agent_runs` bằng migration kế tiếp.
- Giữ ADR/spec/evidence V4 làm historical evaluation record.
- Không mở DeepSeek/provider runtime vì chưa có labeled usefulness target và ADR-008 chỉ cho synthetic extraction.
- Chỉ đánh giá lại agent khi có responsibility mới với frozen labeled dataset, measurable gain target và output không deterministic từ input facts.
```

Include context, responsibility comparison, alternatives, consequences and migration data-loss boundary from the approved design; do not state that a live model was evaluated.

- [ ] **Step 2: Update the ADR index**

Change ADR-012 to `Superseded in part` and add:

```markdown
| [ADR-013](0013-remove-unretained-v4-agent-runtime.md) | Accepted | Loại V4 agent runtime không có measurable usefulness; giữ deterministic paths |
```

State in the candidate-technology paragraph that LangGraph remains deferred and no current agent runtime is accepted.

- [ ] **Step 3: Check and commit the decision**

Run:

```powershell
git diff --check
rg -n "TBD|TODO|placeholder" docs/decisions/0013-remove-unretained-v4-agent-runtime.md
```

Expected: `git diff --check` exits `0`; placeholder scan has no matches.

Commit:

```powershell
git add docs/decisions/0013-remove-unretained-v4-agent-runtime.md docs/decisions/README.md
git commit -m "docs: decide v4 agent runtime removal"
```

### Task 2: Remove the runtime and schema through a tested migration

**Files:**

- Modify: `tests/integration/test_postgresql_schema.py`
- Create: `migrations/versions/a1d4e7f9b203_remove_unretained_agent_runtime.py`
- Modify: `migrations/env.py`
- Delete: `src/devradar/agents/__init__.py`
- Delete: `src/devradar/agents/application.py`
- Delete: `src/devradar/agents/decisions.py`
- Delete: `src/devradar/agents/models.py`
- Delete: `src/devradar/agents/persistence.py`
- Delete: `src/devradar/agents/policy.py`
- Delete: `src/devradar/agents/responsibilities.py`
- Delete: `src/devradar/agents/run_state.py`
- Delete: `src/devradar/agents/workflow.py`
- Delete: `tests/test_agent_application.py`
- Delete: `tests/test_agent_decisions.py`
- Delete: `tests/test_agent_policy.py`
- Delete: `tests/test_agent_responsibilities.py`
- Delete: `tests/test_agent_run_state.py`
- Delete: `tests/test_agent_workflow.py`
- Delete: `tests/integration/test_agent_runs.py`
- Delete: `tests/integration/test_agent_workflow.py`

- [ ] **Step 1: Write the failing head-schema regression**

In `test_migration_and_domain_invariants_on_postgresql`, immediately after the initial two head upgrades, add:

```python
    engine = create_engine(fresh_postgresql_url)
    assert "agent_runs" not in inspect(engine).get_table_names()
    engine.dispose()

    command.downgrade(alembic_config, "f4a6c2d8e901")
    historical_engine = create_engine(fresh_postgresql_url)
    assert "agent_runs" in inspect(historical_engine).get_table_names()
    historical_engine.dispose()

    command.upgrade(alembic_config, "head")
    head_engine = create_engine(fresh_postgresql_url)
    assert "agent_runs" not in inspect(head_engine).get_table_names()
    head_engine.dispose()
```

Keep the existing `command.check(alembic_config)` after the final head upgrade. Reuse the later `engine` variable for domain assertions.

- [ ] **Step 2: Run the regression and observe RED**

Run:

```powershell
docker compose --env-file .env.example up database --wait
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_postgresql_schema.py::test_migration_and_domain_invariants_on_postgresql -q
```

Expected before the new revision: FAIL because current head is `f4a6c2d8e901` and still contains `agent_runs`.

- [ ] **Step 3: Add the removal revision**

Create:

```python
"""Remove the unretained V4 agent runtime audit table."""

from collections.abc import Sequence

from alembic import op
from migrations.versions.f4a6c2d8e901_add_agent_runs import upgrade as recreate_agent_runs

revision: str = "a1d4e7f9b203"
down_revision: str | Sequence[str] | None = "f4a6c2d8e901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("agent_runs")


def downgrade() -> None:
    recreate_agent_runs()
```

The downgrade intentionally recreates the immutable historical schema but cannot restore deleted rows.

- [ ] **Step 4: Remove runtime metadata and code**

In `migrations/env.py`, delete:

```python
from devradar.agents import models as _agent_models
```

and change:

```python
_MODEL_MODULES = (_catalog_models, _ingestion_models, _intelligence_models)
```

Delete the agent package and agent-only tests listed in this task. Do not move code into another module and do not leave compatibility shims.

- [ ] **Step 5: Verify GREEN and absence**

Run:

```powershell
.venv\Scripts\python -m pytest tests/integration/test_postgresql_schema.py::test_migration_and_domain_invariants_on_postgresql -q
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy
rg -n "devradar\.agents|AgentRun|agent_runs|execute_responsibility|evaluate_responsibility" src tests migrations/env.py
```

Expected: tests/static gates pass; final reference scan has no matches. Historical migration files are deliberately excluded from the absence scan.

- [ ] **Step 6: Commit runtime removal**

```powershell
git add migrations src tests
git commit -m "refactor: remove unretained v4 agent runtime"
```

### Task 3: Align current-state documentation

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/AI.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update root state and project instructions**

Use these current-state statements consistently:

```text
V4 complete: planner/validator/analyst proposal paths were evaluated and removed because no measurable usefulness gain existed beyond deterministic V1–V3 facts. LangGraph and provider runtime remain deferred. V5 is the next phase.
```

In `AGENTS.md`, replace the ADR-012 direct-runtime rule with ADR-013: no agent runtime may be reintroduced without a frozen usefulness dataset, measurable improvement gate, privacy boundary and new ADR. Preserve all existing ingestion/security rules and verified commands.

- [ ] **Step 2: Remove current AgentRun/domain claims**

In `docs/DOMAIN_MODEL.md`:

- remove `AgentRun` from the current entity table;
- remove the `AgentRun` entity/lifecycle/invariants sections;
- keep one historical note linking ADR-013 if needed to explain why V4 has no current agent entity;
- keep CV redaction rules, replacing “AgentRun” with generic log/tracing/audit wording.

In `docs/ARCHITECTURE.md`:

- remove `agents` as a current module and remove the active AgentRun flow diagram;
- state that V4 evaluation artifacts are historical and deterministic modules own all current behavior;
- do not claim production provider or analyst workflow exists.

- [ ] **Step 3: Close V4 in roadmap**

Set V4 `complete`. Replace deliverable/demo wording that implies retained runtime with a closeout paragraph mapping:

```markdown
V4-006 áp rule giữ/loại đã đặt trước: cả ba proposal path bị loại vì safe facts đã xác định outcome và không có labeled usefulness gain. Safety/failure boundaries đã được chứng minh bởi V4-001–V4-005; ADR-013 và V4-006 evidence ghi migration removal. V5 tiếp tục dùng deterministic API/analytics hiện hành.
```

Keep the historical V4-001–V4-005 evidence links and make V5 prerequisite read `V4 complete`.

- [ ] **Step 4: Run documentation consistency scans**

```powershell
rg -n "V4-006 Ready|V4.*in_progress|current.*AgentRun|direct.*agent workflow|production.*agent" README.md AGENTS.md docs
git diff --check
```

Expected: no stale current-state claim; only explicitly historical references remain.

- [ ] **Step 5: Commit current-state docs**

```powershell
git add README.md AGENTS.md docs/AI.md docs/ARCHITECTURE.md docs/DOMAIN_MODEL.md docs/ROADMAP.md
git commit -m "docs: align architecture after v4 evaluation"
```

### Task 4: Produce closeout evidence and update the local board

**Files:**

- Create: `docs/evidence/V4-006-agent-usefulness-closeout.md`
- Modify: `README.md`
- Modify: `TASK_BOARD.md` (ignored, never stage)

- [ ] **Step 1: Write evidence from actual command outputs**

The evidence must contain these sections with measured results filled only after commands finish:

```markdown
# V4-006 — Agent usefulness comparison và V4 closeout

**Status:** `complete` ngày 2026-08-22.

## Decision

Planner, validator và analyst reasoning paths đều bị loại theo ADR-013; không có live model usefulness claim.

## Comparison

| Responsibility | Deterministic authority | Missing measurable gain | Outcome |
|---|---|---|---|
| planner | V2 schedule/retry/health | no labeled priority/delay outcome | removed |
| validator | V3 schema/evidence/canonicalization | proposal sees already-computed validity | removed |
| analyst | V3 aggregate + deterministic projection | direction/caveat already exact | removed |

## Removal and migration

Record deleted runtime/tests, new revision, destructive `agent_runs` boundary and round-trip result.

## Verification

Record exact default/PostgreSQL pytest counts, Ruff, format, mypy source count, pip check, Alembic check, Markdown link count and absence scans.

## Exit criteria mapping

Map each V4 criterion to V4-001–V4-005 historical safety evidence or V4-006 removal evidence.
```

Add the evidence link to the README documentation index.

- [ ] **Step 2: Update ignored task board**

Set:

```text
Active phase: v5 (proposed)
V4-006: Done
V5-001: Ready
```

Use the V4-006 evidence path in its Done column. Do not force-add or stage `TASK_BOARD.md`.

- [ ] **Step 3: Verify the board remains ignored and commit evidence**

```powershell
git check-ignore -v TASK_BOARD.md
git status --short
git add README.md docs/evidence/V4-006-agent-usefulness-closeout.md
git commit -m "docs: close v4 after agent usefulness review"
```

Expected: `TASK_BOARD.md` is ignored and absent from staged/committed files.

### Task 5: Run final gates and push the completed phase

**Files:**

- Modify only if a gate reveals a V4-006 defect; no unrelated cleanup.

- [ ] **Step 1: Run full default and PostgreSQL suites**

```powershell
.venv\Scripts\python -m pytest
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: both commands reach final pass output; PostgreSQL suite has no skipped PostgreSQL tests.

- [ ] **Step 2: Run static, dependency and migration gates**

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
$env:DEVRADAR_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/devradar'
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m alembic check
Remove-Item Env:\DEVRADAR_DATABASE_URL
```

Expected: all exit `0`; Alembic reports no new upgrade operations.

- [ ] **Step 3: Validate Markdown and current-state references**

Run the repository's established local Markdown link validator logic over tracked `*.md` files, then:

```powershell
rg -n "devradar\.agents|AgentRun|agent_runs" src tests migrations/env.py
git diff origin/main...HEAD -- requirements.in requirements-dev.in requirements.lock requirements-dev.lock docs/API.md
git diff --check
```

Expected: zero invalid Markdown links; no runtime references; dependency/API diffs empty; no whitespace errors.

- [ ] **Step 4: Final repository and ignored-secret review**

```powershell
git status --short --branch
git check-ignore -v TASK_BOARD.md .env.local
git diff --stat origin/main...HEAD
git log -8 --oneline
```

Expected: tracked tree clean; `TASK_BOARD.md` and `.env.local` ignored; no secret is printed or staged.

- [ ] **Step 5: Preserve data volume, stop Compose and push**

```powershell
docker compose --env-file .env.example down
git push origin main
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
git status --short --branch
```

Expected: teardown does not use `--volumes`; push succeeds; local and remote hashes match; branch is clean and no longer ahead.

