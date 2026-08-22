# V3-003 ExtractionResult Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cài `ExtractionResult` cho job extraction theo deterministic-first, accepted-only cache, validation fail-closed và provider boundary được inject mà không thêm production provider hay dependency mới.

**Architecture:** PostgreSQL là system of record cho mọi extraction attempt. Orchestrator đọc `Job`, chạy deterministic extraction trước, trả accepted rule result nếu đủ; nếu chưa đủ thì lookup accepted cache theo `input_ref` cùng toàn bộ version fields, sau đó mới gọi provider callable ở ngoài transaction ngắn. Mọi persistence dùng transaction ngắn và re-check accepted key để concurrent writer không tạo duplicate accepted result; `rejected` và `needs_review` chỉ phục vụ audit.

**Tech Stack:** Python 3.13, Pydantic 2.x hiện có, SQLAlchemy 2.0, PostgreSQL 18, Alembic, pytest; không thêm SDK, queue, Prefect, Redis, pgvector hoặc endpoint mới.

---

## File map và trách nhiệm

| File | Trách nhiệm |
|---|---|
| `src/devradar/intelligence/evaluation.py` | Expose helper extraction skill mention từ taxonomy alias hiện có; giữ một nguồn alias/evidence cho evaluation và runtime. |
| `src/devradar/intelligence/extraction.py` | Typed payload, deterministic extractor, cache key, strict provider validation, bounded retry và orchestration. |
| `src/devradar/intelligence/models.py` | SQLAlchemy enum và mapping `ExtractionResult`, constraint và accepted-only unique index metadata. |
| `migrations/env.py` | Import intelligence models để Alembic thấy table metadata. |
| `migrations/versions/b7e3f1c4a902_add_extraction_results.py` | Tạo/xóa `extraction_results` và index; không backfill. |
| `tests/test_extraction.py` | Unit contract không cần PostgreSQL: taxonomy, deterministic completeness, validation, retry và redaction. |
| `tests/integration/test_extraction_result.py` | PostgreSQL migration, accepted-only uniqueness, read-after-write, rollback và concurrent insert. |
| `tests/integration/test_postgresql_schema.py` | Bổ sung `extraction_results` vào domain table/invariant smoke. |
| `docs/DOMAIN_MODEL.md` | Thuật ngữ, schema semantics và lifecycle `accepted/rejected/needs_review`. |
| `docs/AI.md` | Boundary deterministic/provider, cache key, retry, privacy và cost metadata của V3-003. |
| `docs/OPERATIONS.md` | Gate migration/integration, metric cache hit/validation failure và runbook provider outage. |
| `docs/evidence/V3-003-extraction-result-cache.md` | Bằng chứng command/test/static gate sau khi chạy implementation. |
| `TASK_BOARD.md` | Cục bộ; chuyển `V3-003` sang `Done`, `V3-004` sang `Ready` chỉ sau khi evidence thực tế tồn tại. |

### Task 1: Chốt typed extraction payload và deterministic boundary

**Files:**
- Modify: `src/devradar/intelligence/evaluation.py`
- Create: `src/devradar/intelligence/extraction.py`
- Create: `tests/test_extraction.py`

- [ ] **Step 1: Viết unit test đỏ cho payload, alias và completeness**

Thêm các test sau vào `tests/test_extraction.py`; test chỉ dùng object `Job` chưa persist và callable fake, không network:

```python
from decimal import Decimal
from uuid import uuid4

from devradar.catalog.models import Job, JobLevel
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    DETERMINISTIC_EXTRACTOR_VERSION,
    ExtractionPayload,
    deterministic_extract,
)


def _job(*, description: str | None, levels: list[str] | None = None) -> Job:
    return Job(
        id=uuid4(),
        source_id=uuid4(),
        canonical_url="https://careers.example.test/jobs/1",
        title="Backend Engineer",
        company_name="Example",
        description_text=description,
        location_raw="Ho Chi Minh City, hybrid",
        location_city="Ho Chi Minh City",
        location_province="Ho Chi Minh City",
        work_mode="hybrid",
        salary_raw="30-40 triệu VND/tháng",
        salary_min=Decimal("30000000"),
        salary_max=Decimal("40000000"),
        currency="VND",
        salary_period="month",
        level_raw="Senior",
        levels=levels or [JobLevel.SENIOR.value],
        experience_min=Decimal("3"),
        experience_max=None,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        current_snapshot_id=uuid4(),
        job_content_hash="a" * 64,
    )


def test_deterministic_extraction_is_complete_without_provider() -> None:
    result = deterministic_extract(
        _job(description="Build APIs with Python and PostgreSQL; Docker is a plus.")
    )

    assert result.complete is True
    assert result.extractor_version == DETERMINISTIC_EXTRACTOR_VERSION
    assert result.payload.levels == (JobLevel.SENIOR,)
    assert {skill.name for skill in result.payload.skills} == {"python", "postgresql", "docker"}
    assert CANONICALIZATION_VERSION == "extraction-canonicalization-v1"


def test_deterministic_extraction_is_incomplete_when_skill_evidence_is_missing() -> None:
    result = deterministic_extract(_job(description="Join a backend team."))

    assert result.complete is False
    assert result.warnings == ("skills_not_determined",)


def test_payload_rejects_extra_fields_and_invalid_skill_evidence() -> None:
    payload = {
        "levels": ["senior"],
        "experience": {"minimumYears": 3, "maximumYears": None},
        "salary": {"minimum": 30, "maximum": 40, "currency": "VND", "period": "month"},
        "location": {"city": "Hanoi", "province": "Hanoi", "workMode": "onsite"},
        "skills": [{"name": "python", "requirementType": "required", "evidence": "Python"}],
        "untrusted": "must be rejected",
    }

    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate(payload)
```

Import `datetime`, `UTC`, `pytest` và `ValidationError` ở đầu test file. Các assertion buộc runtime phải dùng alias map hiện có, không tự tạo taxonomy thứ hai.

- [ ] **Step 2: Chạy test đỏ và xác nhận thiếu module/helper**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -q
```

Expected: FAIL vì `devradar.intelligence.extraction` và helper skill mention chưa tồn tại; không coi lỗi import là pass.

- [ ] **Step 3: Expose helper taxonomy và viết implementation typed tối thiểu**

Trong `evaluation.py`, thêm helper công khai dùng chính `_SKILL_PATTERNS`, `_OPTIONAL_MARKERS`, `_NEGATED_MARKERS`:

```python
def extract_skill_expectations(title: str, description_text: str) -> tuple[SkillExpectation, ...]:
    source_text = f"{title}\n{description_text}"
    labels: dict[str, tuple[RequirementType, str]] = {}
    for clause in (part.strip() for part in re.split(r"[\n;]+", source_text) if part.strip()):
        folded = clause.casefold()
        if any(marker in folded for marker in _NEGATED_MARKERS):
            continue
        requirement_type = (
            RequirementType.OPTIONAL
            if any(marker in folded for marker in _OPTIONAL_MARKERS)
            else RequirementType.REQUIRED
        )
        for name, patterns in _SKILL_PATTERNS.items():
            match = next((pattern.search(clause) for pattern in patterns if pattern.search(clause)), None)
            if match is None:
                continue
            previous = labels.get(name)
            if previous is None or requirement_type is RequirementType.REQUIRED:
                labels[name] = (requirement_type, match.group(0))
    return tuple(
        SkillExpectation(name=name, requirement_type=kind, evidence=evidence)
        for name, (kind, evidence) in sorted(labels.items())
    )

Refactor `_extract_skill_labels` to derive its labels from this helper so evaluation and runtime cannot diverge:

```python
def _extract_skill_labels(case: EvaluationCase) -> set[tuple[str, RequirementType]]:
    return {
        (skill.name, skill.requirement_type)
        for skill in extract_skill_expectations(case.input.title, case.input.description_text)
    }
```

Create `src/devradar/intelligence/extraction.py` with the payload and deterministic boundary. Reuse the Pydantic field models from `evaluation.py`; do not add a second alias map:

```python
"""Deterministic-first extraction contract and provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from devradar.catalog.models import Job, JobLevel
from devradar.intelligence.evaluation import (
    EvaluationModel,
    ExperienceExpectation,
    LocationExpectation,
    SalaryExpectation,
    SkillExpectation,
    extract_skill_expectations,
)

DETERMINISTIC_EXTRACTOR_VERSION = "deterministic-job-v1"
EXTRACTION_SCHEMA_VERSION = "job-extraction-schema-v1"
CANONICALIZATION_VERSION = "extraction-canonicalization-v1"


class ExtractionPayload(EvaluationModel):
    levels: tuple[JobLevel, ...]
    experience: ExperienceExpectation
    salary: SalaryExpectation
    location: LocationExpectation
    skills: tuple[SkillExpectation, ...]


@dataclass(frozen=True, slots=True)
class DeterministicExtraction:
    payload: ExtractionPayload
    complete: bool
    extractor_version: str
    warnings: tuple[str, ...] = ()


def _decimal(value: Decimal | None) -> Decimal | None:
    return value


def deterministic_extract(job: Job) -> DeterministicExtraction:
    warnings: list[str] = []
    try:
        levels = tuple(JobLevel(value) for value in job.levels)
    except ValueError:
        levels = ()
        warnings.append("levels_invalid")

    description = job.description_text or ""
    skills = extract_skill_expectations(job.title, description)
    if not skills:
        warnings.append("skills_not_determined")

    payload = ExtractionPayload(
        levels=levels,
        experience=ExperienceExpectation(
            minimum_years=_decimal(job.experience_min), maximum_years=_decimal(job.experience_max)
        ),
        salary=SalaryExpectation(
            minimum=_decimal(job.salary_min),
            maximum=_decimal(job.salary_max),
            currency=job.currency,
            period=job.salary_period,
        ),
        location=LocationExpectation(
            city=job.location_city,
            province=job.location_province,
            work_mode=job.work_mode,
        ),
        skills=skills,
    )
    return DeterministicExtraction(
        payload=payload,
        complete=not warnings and bool(description),
        extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
        warnings=tuple(warnings),
    )


def safe_validation_errors(error: ValidationError, *, code: str) -> list[dict[str, str]]:
    """Keep only bounded code/path/type; never serialize rejected values."""

    return [
        {
            "code": code,
            "path": ".".join(str(part) for part in item["loc"])[:120],
            "type": str(item["type"])[:80],
        }
        for item in error.errors()
    ][:16]
```

The `salary.period` and `location.work_mode` assignments above must convert persisted strings with the existing `SalaryPeriod` and `WorkMode` enums before constructing the Pydantic models; invalid values append `salary_invalid` or `location_invalid` and use `None`. This keeps scalar precedence deterministic and makes malformed persisted state fail closed.

- [ ] **Step 4: Chạy unit test xanh và kiểm tra static hẹp**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -q
.venv\Scripts\python -m ruff check src/devradar/intelligence/evaluation.py src/devradar/intelligence/extraction.py tests/test_extraction.py
.venv\Scripts\python -m mypy src/devradar/intelligence/evaluation.py src/devradar/intelligence/extraction.py tests/test_extraction.py
```

Expected: all new unit tests pass; Ruff và mypy kết thúc exit code `0`.

- [ ] **Step 5: Commit contract boundary**

```powershell
git add src/devradar/intelligence/evaluation.py src/devradar/intelligence/extraction.py tests/test_extraction.py
git commit -m "feat: add deterministic extraction contract"
```

### Task 2: Tạo `ExtractionResult` mapping và Alembic migration

**Files:**
- Create: `src/devradar/intelligence/models.py`
- Modify: `migrations/env.py`
- Create: `migrations/versions/b7e3f1c4a902_add_extraction_results.py`
- Modify: `tests/integration/test_postgresql_schema.py`
- Create: `tests/integration/test_extraction_result.py`

- [ ] **Step 1: Viết integration test đỏ cho table, constraints và migration idempotency**

Trong `tests/integration/test_extraction_result.py`, dùng `_alembic_config`, `fresh_postgresql_url` và một persisted `Job` fixture theo pattern của `tests/integration/test_postgresql_schema.py`. Test contract trước khi migration chạy:

```python
@pytest.mark.postgresql
def test_extraction_result_table_and_constraints_on_fresh_postgresql(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(_alembic_config(), "head")
    command.upgrade(_alembic_config(), "head")
    command.check(_alembic_config())

    engine = create_engine(fresh_postgresql_url)
    inspector = inspect(engine)
    assert "extraction_results" in inspector.get_table_names()
    check_names = {check["name"] for check in inspector.get_check_constraints("extraction_results")}
    assert {
        "ck_extraction_results_input_hash",
        "ck_extraction_results_status",
        "ck_extraction_results_confidence",
        "ck_extraction_results_non_negative_metrics",
    } <= check_names
    indexes = {index["name"] for index in inspector.get_indexes("extraction_results")}
    assert "uq_extraction_results_accepted_cache" in indexes
```

Thêm `extraction_results` vào `DOMAIN_TABLES` trong `tests/integration/test_postgresql_schema.py` để schema smoke kiểm tra cả domain table mới.

- [ ] **Step 2: Chạy integration test đỏ khi mapping/migration chưa tồn tại**

Run:

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_extraction_result.py -m postgresql -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: FAIL do migration chưa có table/index; nếu biến môi trường không có PostgreSQL thì test phải `skipped`, không được gọi đó là pass.

- [ ] **Step 3: Viết SQLAlchemy mapping với safe partial unique cache index**

Tạo `src/devradar/intelligence/models.py` theo mapping này; expression `coalesce` làm `NULL` của `prompt_version`/`model` có cùng cache identity cho rule result:

```python
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


class ExtractionInputType(StrEnum):
    JOB = "job"


class ExtractionType(StrEnum):
    RULE = "rule"
    LLM = "llm"


class ExtractionValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class ExtractionResult(Base):
    __tablename__ = "extraction_results"
    __table_args__ = (
        CheckConstraint("input_type = 'job'", name="ck_extraction_results_input_type"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_extraction_results_input_hash"),
        CheckConstraint(
            "extractor_type IN ('rule', 'llm')", name="ck_extraction_results_extractor_type"
        ),
        CheckConstraint(
            "validation_status IN ('accepted', 'rejected', 'needs_review')",
            name="ck_extraction_results_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_extraction_results_confidence",
        ),
        CheckConstraint(
            "(latency_ms IS NULL OR latency_ms >= 0) AND "
            "(prompt_tokens IS NULL OR prompt_tokens >= 0) AND "
            "(completion_tokens IS NULL OR completion_tokens >= 0) AND "
            "(estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
            name="ck_extraction_results_non_negative_metrics",
        ),
        Index(
            "uq_extraction_results_accepted_cache",
            "input_type",
            "input_ref",
            "input_hash",
            "extractor_type",
            "extractor_version",
            "schema_version",
            text("coalesce(prompt_version, '')"),
            text("coalesce(model, '')"),
            "canonicalization_version",
            unique=True,
            postgresql_where=text("validation_status = 'accepted'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    input_type: Mapped[ExtractionInputType] = mapped_column(String(16))
    input_ref: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT")
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    extractor_type: Mapped[ExtractionType] = mapped_column(String(16))
    extractor_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    canonicalization_version: Mapped[str] = mapped_column(String(100))
    output_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation_status: Mapped[ExtractionValidationStatus] = mapped_column(String(16))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    validation_errors: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
```

Use the existing `_enum_values` convention only if switching to SQLAlchemy `Enum`; string columns plus database `CheckConstraint` match existing schema and avoid duplicate Python/SQL enum naming. Keep the foreign key to `jobs.id`, so every result retains canonical Job provenance.

- [ ] **Step 4: Register mapping and write migration without backfill**

In `migrations/env.py`, import `devradar.intelligence.models` and add it to `_MODEL_MODULES`. Create `migrations/versions/b7e3f1c4a902_add_extraction_results.py` with `down_revision = "d9216c7fb40e"`. The migration must:

1. Create the table with this complete Alembic column/constraint definition (imports are `import sqlalchemy as sa` and `from sqlalchemy.dialects import postgresql`):

```python
op.create_table(
    "extraction_results",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("input_type", sa.String(16), nullable=False),
    sa.Column("input_ref", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("input_hash", sa.String(64), nullable=False),
    sa.Column("extractor_type", sa.String(16), nullable=False),
    sa.Column("extractor_version", sa.String(100), nullable=False),
    sa.Column("schema_version", sa.String(100), nullable=False),
    sa.Column("prompt_version", sa.String(100), nullable=True),
    sa.Column("model", sa.String(200), nullable=True),
    sa.Column("canonicalization_version", sa.String(100), nullable=False),
    sa.Column("output_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("validation_status", sa.String(16), nullable=False),
    sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
    sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("latency_ms", sa.Integer(), nullable=True),
    sa.Column("prompt_tokens", sa.Integer(), nullable=True),
    sa.Column("completion_tokens", sa.Integer(), nullable=True),
    sa.Column("estimated_cost_usd", sa.Numeric(14, 8), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.ForeignKeyConstraint(["input_ref"], ["jobs.id"], name="fk_extraction_results_input_ref_jobs", ondelete="RESTRICT"),
    sa.PrimaryKeyConstraint("id"),
    sa.CheckConstraint("input_type = 'job'", name="ck_extraction_results_input_type"),
    sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_extraction_results_input_hash"),
    sa.CheckConstraint("extractor_type IN ('rule', 'llm')", name="ck_extraction_results_extractor_type"),
    sa.CheckConstraint("validation_status IN ('accepted', 'rejected', 'needs_review')", name="ck_extraction_results_status"),
    sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_extraction_results_confidence"),
    sa.CheckConstraint(
        "(latency_ms IS NULL OR latency_ms >= 0) AND (prompt_tokens IS NULL OR prompt_tokens >= 0) AND "
        "(completion_tokens IS NULL OR completion_tokens >= 0) AND (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
        name="ck_extraction_results_non_negative_metrics",
    ),
)
2. Create the named checks exactly as in the mapping.
3. Execute this exact PostgreSQL index statement so nullable version fields share one key:

```python
op.execute(
    sa.text(
        "CREATE UNIQUE INDEX uq_extraction_results_accepted_cache "
        "ON extraction_results (input_type, input_ref, input_hash, extractor_type, "
        "extractor_version, schema_version, coalesce(prompt_version, ''), "
        "coalesce(model, ''), canonicalization_version) "
        "WHERE validation_status = 'accepted'"
    )
)
```

4. In `downgrade`, drop the index first, then table; do not delete or transform existing Job rows because migration has no backfill.

- [ ] **Step 5: Chạy migration/integration test xanh**

Run the PostgreSQL command from Step 2, then the existing schema smoke:

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_extraction_result.py tests/integration/test_postgresql_schema.py -m postgresql -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: migration upgrade twice, `alembic check`, table/check/index assertions and existing domain invariants pass.

- [ ] **Step 6: Commit persistence schema**

```powershell
git add src/devradar/intelligence/models.py migrations/env.py migrations/versions/b7e3f1c4a902_add_extraction_results.py tests/integration/test_extraction_result.py tests/integration/test_postgresql_schema.py
git commit -m "feat: persist extraction results"
```

### Task 3: Implement accepted-only cache key and persistence

**Files:**
- Modify: `src/devradar/intelligence/extraction.py`
- Modify: `tests/test_extraction.py`
- Modify: `tests/integration/test_extraction_result.py`

- [ ] **Step 1: Viết test đỏ cho cache identity và status policy**

Add pure key tests and PostgreSQL persistence tests:

```python
def test_cache_key_changes_for_each_version_dimension() -> None:
    base = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=uuid4(),
        input_hash="a" * 64,
        extractor_type=ExtractionType.LLM,
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="prompt-v1",
        model="test-model",
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    for field in (
        "input_hash",
        "extractor_version",
        "schema_version",
        "prompt_version",
        "model",
        "canonicalization_version",
    ):
        changed = replace(base, **{field: "b" * 64 if field == "input_hash" else "changed"})
        assert changed != base


@pytest.mark.postgresql
def test_rejected_and_needs_review_are_audit_rows_but_never_cache_hits(
    session: Session, key: ExtractionCacheKey
) -> None:
    first, _ = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.REJECTED,
        validation_errors=[{"code": "bad", "path": "skills", "type": "invalid"}],
    )
    second, _ = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.NEEDS_REVIEW,
        validation_errors=[{"code": "timeout", "path": "provider", "type": "transient"}],
    )
    session.commit()
    assert first.id != second.id
    assert load_accepted_cache(session, key) is None
```

The integration test must use one persisted `Job`, the same complete cache key, deterministic output payload only, and no raw description in `validation_errors`.

- [ ] **Step 2: Chạy test đỏ trước khi thêm cache helpers**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -k cache -q
```

Expected: FAIL with missing `ExtractionCacheKey`, `load_accepted_cache` or `persist_extraction_result`.

- [ ] **Step 3: Thêm cache key, lookup và safe persistence**

Add these exact typed boundaries to `extraction.py`:

```python
@dataclass(frozen=True, slots=True)
class ExtractionCacheKey:
    input_type: ExtractionInputType
    input_ref: UUID
    input_hash: str
    extractor_type: ExtractionType
    extractor_version: str
    schema_version: str
    prompt_version: str | None
    model: str | None
    canonicalization_version: str


def load_accepted_cache(session: Session, key: ExtractionCacheKey) -> ExtractionResult | None:
    return session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.input_type == key.input_type.value,
            ExtractionResult.input_ref == key.input_ref,
            ExtractionResult.input_hash == key.input_hash,
            ExtractionResult.extractor_type == key.extractor_type.value,
            ExtractionResult.extractor_version == key.extractor_version,
            ExtractionResult.schema_version == key.schema_version,
            ExtractionResult.prompt_version.is_not_distinct_from(key.prompt_version),
            ExtractionResult.model.is_not_distinct_from(key.model),
            ExtractionResult.canonicalization_version == key.canonicalization_version,
            ExtractionResult.validation_status == ExtractionValidationStatus.ACCEPTED.value,
        )
    )


def persist_extraction_result(
    session: Session,
    *,
    key: ExtractionCacheKey,
    output_data: dict[str, Any],
    status: ExtractionValidationStatus,
    validation_errors: list[dict[str, str]] | None,
    confidence: Decimal | None = None,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    estimated_cost_usd: Decimal | None = None,
) -> tuple[ExtractionResult, bool]:
    if status is ExtractionValidationStatus.ACCEPTED:
        existing = load_accepted_cache(session, key)
        if existing is not None:
            return existing, True
    result = ExtractionResult(
        input_type=key.input_type.value,
        input_ref=key.input_ref,
        input_hash=key.input_hash,
        extractor_type=key.extractor_type.value,
        extractor_version=key.extractor_version,
        schema_version=key.schema_version,
        prompt_version=key.prompt_version,
        model=key.model,
        canonicalization_version=key.canonicalization_version,
        output_data=output_data,
        validation_status=status.value,
        validation_errors=validation_errors,
        confidence=confidence,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )
    session.add(result)
    session.flush()
    return result, False
```

Use `is_not_distinct_from` for the read query and the migration expression index for the write race. Catch a duplicate accepted `IntegrityError` inside `session.begin_nested()`, rollback only the savepoint, re-read the accepted row and return `(row, True)`; never swallow a different integrity error.

- [ ] **Step 4: Chạy unit và PostgreSQL cache tests xanh**

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -k cache -q
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_extraction_result.py -m postgresql -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: accepted same-key write returns cache hit; rejected/needs-review writes get distinct IDs and never satisfy the accepted lookup; changing any version dimension produces a miss.

- [ ] **Step 5: Commit cache persistence**

```powershell
git add src/devradar/intelligence/extraction.py tests/test_extraction.py tests/integration/test_extraction_result.py
git commit -m "feat: add accepted extraction cache"
```

### Task 4: Add strict provider boundary, bounded retry and orchestration

**Files:**
- Modify: `src/devradar/intelligence/extraction.py`
- Modify: `tests/test_extraction.py`

- [ ] **Step 1: Viết unit test đỏ cho provider policy**

Add pure resolver tests covering provider success, missing provider, transient retry and malformed output. Cache-hit and complete-deterministic zero-call tests use PostgreSQL-backed `extract_job` in Task 5, because they must exercise the real cache transaction:

```python
def test_provider_success_keeps_deterministic_scalars() -> None:
    calls = 0

    def provider(_request: ProviderRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "levels": ["intern"],
            "experience": {"minimumYears": 99, "maximumYears": 100},
            "salary": {"minimum": 1, "maximum": 2, "currency": "USD", "period": "year"},
            "location": {"city": "Hanoi", "province": "Hanoi", "workMode": "remote"},
            "skills": [],
        }

    resolution = resolve_provider_fallback(
        deterministic=_incomplete_deterministic(),
        source_text="Backend Engineer\nJoin the team.",
        request=_provider_request(),
        provider=provider,
        metadata=TEST_PROVIDER,
    )
    assert calls == 1
    assert resolution.status is ExtractionValidationStatus.ACCEPTED
    assert resolution.payload.levels == (JobLevel.SENIOR,)
    assert resolution.payload.salary.currency == "VND"


def test_missing_provider_becomes_needs_review() -> None:
    resolution = resolve_provider_fallback(
        deterministic=_incomplete_deterministic(),
        source_text="Backend Engineer\nJoin the team.",
        request=_provider_request(),
        provider=None,
        metadata=TEST_PROVIDER,
    )
    assert resolution.status is ExtractionValidationStatus.NEEDS_REVIEW
    assert resolution.errors == [
        {"code": "provider_not_configured", "path": "provider", "type": "missing"}
    ]


def test_transient_provider_failure_attempts_twice_then_needs_review() -> None:
    calls = 0

    def provider(_request: ProviderRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise ProviderTransientError("provider_timeout")

    resolution = resolve_provider_fallback(
        deterministic=_incomplete_deterministic(),
        source_text="Backend Engineer\nJoin the team.",
        request=_provider_request(),
        provider=provider,
        metadata=TEST_PROVIDER,
    )
    assert calls == 2
    assert resolution.status is ExtractionValidationStatus.NEEDS_REVIEW
    assert resolution.payload == _incomplete_deterministic().payload


def test_malformed_provider_candidate_is_rejected_without_raw_value() -> None:
    resolution = resolve_provider_fallback(
        deterministic=_incomplete_deterministic(),
        source_text="Backend Engineer\nJoin the team.",
        request=_provider_request(),
        provider=lambda _request: {"secret": "not-persisted", "skills": []},
        metadata=TEST_PROVIDER,
    )
    assert resolution.status is ExtractionValidationStatus.REJECTED
    assert all("not-persisted" not in json.dumps(error) for error in resolution.errors)
```

Define the test helpers immediately above these tests, with no external provider calls:

```python
TEST_PROVIDER = ProviderMetadata(
    extractor_version="provider-boundary-v1",
    schema_version=EXTRACTION_SCHEMA_VERSION,
    prompt_version="test-prompt-v1",
    model="test-model",
    canonicalization_version=CANONICALIZATION_VERSION,
)


def _incomplete_deterministic() -> DeterministicExtraction:
    return DeterministicExtraction(
        payload=ExtractionPayload(
            levels=(JobLevel.SENIOR,),
            experience=ExperienceExpectation(minimum_years=Decimal("3"), maximum_years=None),
            salary=SalaryExpectation(
                minimum=Decimal("30000000"),
                maximum=Decimal("40000000"),
                currency="VND",
                period=SalaryPeriod.MONTH,
            ),
            location=LocationExpectation(
                city="Ho Chi Minh City", province="Ho Chi Minh City", work_mode=WorkMode.HYBRID
            ),
            skills=(),
        ),
        complete=False,
        extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
        warnings=("skills_not_determined",),
    )


def _provider_request() -> ProviderRequest:
    deterministic = _incomplete_deterministic()
    return ProviderRequest(
        input_ref=uuid4(),
        input_hash="a" * 64,
        title="Backend Engineer",
        description_text="Join the team.",
        deterministic_payload=deterministic.payload,
    )
```

Import `Decimal`, `uuid4`, `JobLevel`, `SalaryPeriod`, `WorkMode`, `ExperienceExpectation`, `SalaryExpectation`, `LocationExpectation`, `DeterministicExtraction`, `ExtractionPayload`, `ProviderMetadata`, `ProviderRequest`, `ProviderTransientError`, `resolve_provider_fallback`, `EXTRACTION_SCHEMA_VERSION`, `DETERMINISTIC_EXTRACTOR_VERSION`, and `CANONICALIZATION_VERSION` at the top of the test module.

- [ ] **Step 2: Chạy test đỏ để khóa missing provider symbols**

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -k provider -q
```

Expected: FAIL because `ProviderRequest`, `ProviderMetadata`, `ProviderTransientError`, `resolve_provider_fallback` and `ExtractionResolution` are not yet defined.

- [ ] **Step 3: Implement typed provider boundary and validator**

Add these contracts and the pure fallback resolver to `extraction.py`:

```python
MAX_PROVIDER_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    extractor_version: str
    schema_version: str
    prompt_version: str
    model: str
    canonicalization_version: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    input_ref: UUID
    input_hash: str
    title: str
    description_text: str
    deterministic_payload: ExtractionPayload


ProviderCallable = Callable[[ProviderRequest], Mapping[str, object]]


class ProviderTransientError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExtractionResolution:
    payload: ExtractionPayload
    status: ExtractionValidationStatus
    errors: list[dict[str, str]] | None
    attempts: int


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    result: ExtractionResult
    deterministic: DeterministicExtraction
    cache_hit: bool
    attempts: int


class ProviderValidationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_provider_candidate(
    candidate: Mapping[str, object],
    *,
    deterministic: DeterministicExtraction,
    source_text: str,
) -> ExtractionPayload:
    try:
        payload = ExtractionPayload.model_validate(candidate)
    except ValidationError:
        raise ProviderValidationError("provider_schema_invalid") from None
    merged = payload.model_copy(
        update={
            "levels": deterministic.payload.levels,
            "experience": deterministic.payload.experience,
            "salary": deterministic.payload.salary,
            "location": deterministic.payload.location,
        }
    )
    keys = [(skill.name, skill.requirement_type) for skill in merged.skills]
    if len(keys) != len(set(keys)) or any(
        skill.evidence not in source_text for skill in merged.skills
    ):
        raise ProviderValidationError("provider_evidence_invalid")
    return merged


def resolve_provider_fallback(
    *,
    deterministic: DeterministicExtraction,
    source_text: str,
    request: ProviderRequest,
    provider: ProviderCallable | None,
    metadata: ProviderMetadata,
) -> ExtractionResolution:
    if provider is None:
        return ExtractionResolution(
            payload=deterministic.payload,
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            errors=[{"code": "provider_not_configured", "path": "provider", "type": "missing"}],
            attempts=0,
        )
    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            candidate = provider(request)
            payload = validate_provider_candidate(
                candidate, deterministic=deterministic, source_text=source_text
            )
            return ExtractionResolution(
                payload=payload,
                status=ExtractionValidationStatus.ACCEPTED,
                errors=None,
                attempts=attempt,
            )
        except ProviderValidationError as error:
            return ExtractionResolution(
                payload=deterministic.payload,
                status=ExtractionValidationStatus.REJECTED,
                errors=[{"code": error.code, "path": "provider", "type": "validation"}],
                attempts=attempt,
            )
        except ProviderTransientError as error:
            if attempt == MAX_PROVIDER_ATTEMPTS:
                return ExtractionResolution(
                    payload=deterministic.payload,
                    status=ExtractionValidationStatus.NEEDS_REVIEW,
                    errors=[{"code": error.code, "path": "provider", "type": "transient"}],
                    attempts=attempt,
                )
    raise AssertionError("provider resolver must return within the bounded attempt loop")
```

`ProviderValidationError` must carry only its bounded `code`. Before `model_validate`, canonicalize each candidate skill name with `canonicalize_skill_name` and reject unknown/unsupported fields through `EvaluationModel(extra="forbid")`. Do not put the candidate, source text, prompt or exception detail in a raised message or `validation_errors`.

- [ ] **Step 4: Implement deterministic-first orchestration with two short persistence windows**

Implement `extract_job(session, *, job, provider, provider_metadata, clock)` with this exact order:

1. Call `deterministic_extract(job)` before any provider branch.
2. Build a `rule` `ExtractionCacheKey` using `DETERMINISTIC_EXTRACTOR_VERSION`, `EXTRACTION_SCHEMA_VERSION`, `None`, `None` and `CANONICALIZATION_VERSION`.
3. If complete, call `persist_extraction_result` with `accepted`, return it and never evaluate `provider`.
4. If incomplete, require `provider_metadata` only for the LLM key; lookup accepted cache before provider call and return a cache hit.
5. End/rollback the short read transaction before calling provider; provider receives only `ProviderRequest` and has no session/tool/URL capability.
6. If provider is `None`, persist deterministic payload as `needs_review` with exactly `[{"code":"provider_not_configured","path":"provider","type":"missing"}]`.
7. For a candidate, validate/canonicalize; accepted payload preserves deterministic scalar fields. A `ProviderValidationError` persists `rejected` immediately and makes no second call. A `ProviderTransientError` retries exactly once, then persists `needs_review` with the last safe code.
8. Before every accepted insert, re-run `load_accepted_cache` in a fresh transaction. If a concurrent accepted row wins, return it with `cache_hit=True`; otherwise insert the result. Persist only `model_dump(mode="json", by_alias=True)` and bounded usage/latency/cost metadata.

The implementation must not call `session.commit()` while executing provider code and must not keep a row lock or transaction open across a provider call. No DeepSeek/OpenAI/HTTP adapter is added in this task.

Use this orchestration skeleton so the transaction boundary is explicit and testable:

```python
def extract_job(
    session: Session,
    *,
    job: Job,
    provider: ProviderCallable | None,
    provider_metadata: ProviderMetadata | None,
) -> ExtractionOutcome:
    deterministic = deterministic_extract(job)
    rule_key = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=job.id,
        input_hash=job.job_content_hash,
        extractor_type=ExtractionType.RULE,
        extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version=None,
        model=None,
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    if deterministic.complete:
        with session.begin():
            result, cache_hit = persist_extraction_result(
                session,
                key=rule_key,
                output_data=deterministic.payload.model_dump(mode="json", by_alias=True),
                status=ExtractionValidationStatus.ACCEPTED,
                validation_errors=None,
            )
        return ExtractionOutcome(result, deterministic, cache_hit, 0)

    if provider_metadata is None:
        provider_metadata = ProviderMetadata(
            extractor_version="provider-boundary-v1",
            schema_version=EXTRACTION_SCHEMA_VERSION,
            prompt_version="unconfigured",
            model="unconfigured",
            canonicalization_version=CANONICALIZATION_VERSION,
        )
    llm_key = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=job.id,
        input_hash=job.job_content_hash,
        extractor_type=ExtractionType.LLM,
        extractor_version=provider_metadata.extractor_version,
        schema_version=provider_metadata.schema_version,
        prompt_version=provider_metadata.prompt_version,
        model=provider_metadata.model,
        canonicalization_version=provider_metadata.canonicalization_version,
    )
    with session.begin():
        cached = load_accepted_cache(session, llm_key)
    if cached is not None:
        return ExtractionOutcome(cached, deterministic, True, 0)

    session.rollback()
    request = ProviderRequest(
        input_ref=job.id,
        input_hash=job.job_content_hash,
        title=job.title,
        description_text=job.description_text or "",
        deterministic_payload=deterministic.payload,
    )
    resolution = resolve_provider_fallback(
        deterministic=deterministic,
        source_text=f"{job.title}\n{job.description_text or ''}",
        request=request,
        provider=provider,
        metadata=provider_metadata,
    )
    with session.begin():
        result, cache_hit = persist_extraction_result(
            session,
            key=llm_key,
            output_data=resolution.payload.model_dump(mode="json", by_alias=True),
            status=resolution.status,
            validation_errors=resolution.errors,
        )
    return ExtractionOutcome(result, deterministic, cache_hit, resolution.attempts)
```

The caller must provide a clean `Session` with no outer transaction; the function owns only the three short database windows shown above. The provider callable is invoked between `session.rollback()` and the final `with session.begin()`, so it cannot hold a row lock or open DB transaction.

- [ ] **Step 5: Chạy all extraction unit tests và static checks xanh**

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -q
.venv\Scripts\python -m ruff check src/devradar/intelligence tests/test_extraction.py
.venv\Scripts\python -m ruff format --check src/devradar/intelligence tests/test_extraction.py
.venv\Scripts\python -m mypy src/devradar/intelligence tests/test_extraction.py
```

Expected: every branch above has a passing test, no raw rejected value appears in safe error/output, and all static commands exit `0`.

- [ ] **Step 6: Commit orchestration**

```powershell
git add src/devradar/intelligence/extraction.py tests/test_extraction.py
git commit -m "feat: add bounded extraction orchestration"
```

### Task 5: Verify PostgreSQL uniqueness, rollback và concurrent writer behavior

**Files:**
- Modify: `tests/integration/test_extraction_result.py`
- Modify: `src/devradar/intelligence/extraction.py` only if a test exposes a persistence race or transaction bug

- [ ] **Step 1: Add integration tests for read-after-write, rollback and concurrent accepted insert**

Use two SQLAlchemy `Session` objects against the same fresh PostgreSQL database and a committed `Job`:

```python
def _payload() -> dict[str, object]:
    return {
        "levels": ["senior"],
        "experience": {"minimumYears": 3, "maximumYears": None},
        "salary": {"minimum": 30000000, "maximum": 40000000, "currency": "VND", "period": "month"},
        "location": {
            "city": "Ho Chi Minh City",
            "province": "Ho Chi Minh City",
            "workMode": "hybrid",
        },
        "skills": [],
    }


def _key(job: Job) -> ExtractionCacheKey:
    return ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=job.id,
        input_hash=job.job_content_hash,
        extractor_type=ExtractionType.LLM,
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="test-prompt-v1",
        model="test-model",
        canonicalization_version=CANONICALIZATION_VERSION,
    )


@pytest.mark.postgresql
def test_complete_deterministic_job_never_calls_provider(
    session: Session, complete_job: Job
) -> None:
    calls = 0

    def provider(_request: ProviderRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _payload()

    outcome = extract_job(
        session,
        job=complete_job,
        provider=provider,
        provider_metadata=ProviderMetadata(
            extractor_version="provider-boundary-v1",
            schema_version=EXTRACTION_SCHEMA_VERSION,
            prompt_version="test-prompt-v1",
            model="test-model",
            canonicalization_version=CANONICALIZATION_VERSION,
        ),
    )
    assert outcome.result.extractor_type == ExtractionType.RULE.value
    assert outcome.result.validation_status == ExtractionValidationStatus.ACCEPTED.value
    assert calls == 0


@pytest.mark.postgresql
def test_accepted_cache_hit_never_calls_provider(session: Session, incomplete_job: Job) -> None:
    metadata = ProviderMetadata(
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="test-prompt-v1",
        model="test-model",
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    key = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=incomplete_job.id,
        input_hash=incomplete_job.job_content_hash,
        extractor_type=ExtractionType.LLM,
        extractor_version=metadata.extractor_version,
        schema_version=metadata.schema_version,
        prompt_version=metadata.prompt_version,
        model=metadata.model,
        canonicalization_version=metadata.canonicalization_version,
    )
    seed, _ = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    session.commit()
    calls = 0

    def provider(_request: ProviderRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _payload()

    outcome = extract_job(
        session, job=incomplete_job, provider=provider, provider_metadata=metadata
    )
    assert outcome.result.id == seed.id
    assert outcome.cache_hit is True
    assert calls == 0


@pytest.mark.postgresql
def test_accepted_cache_is_unique_but_rejected_rows_are_repeatable(
    session: Session, job: Job
) -> None:
    key = _key(job)
    first, first_hit = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    session.commit()
    second, second_hit = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    assert second.id == first.id
    assert first_hit is False
    assert second_hit is True
    rejected_one, _ = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.REJECTED,
        validation_errors=[{"code": "bad", "path": "skills", "type": "invalid"}],
    )
    rejected_two, _ = persist_extraction_result(
        session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.REJECTED,
        validation_errors=[{"code": "bad", "path": "skills", "type": "invalid"}],
    )
    session.commit()
    assert rejected_one.id != rejected_two.id


@pytest.mark.postgresql
def test_failed_transaction_leaves_no_half_result(session: Session, job: Job) -> None:
    persist_extraction_result(
        session,
        key=_key(job),
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    session.rollback()
    assert session.scalar(select(ExtractionResult)) is None


@pytest.mark.postgresql
def test_second_concurrent_accepted_writer_reads_winner(
    first_session: Session, second_session: Session, job: Job
) -> None:
    key = _key(job)
    first, _ = persist_extraction_result(
        first_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    first_session.commit()
    second, hit = persist_extraction_result(
        second_session,
        key=key,
        output_data=_payload(),
        status=ExtractionValidationStatus.ACCEPTED,
        validation_errors=None,
    )
    assert second.id == first.id
    assert hit is True


@pytest.fixture
def complete_job(session: Session, job: Job) -> Job:
    job.description_text = "Build APIs with Python and PostgreSQL; Docker is a plus."
    session.commit()
    return job


@pytest.fixture
def incomplete_job(session: Session, job: Job) -> Job:
    job.description_text = "Join the backend team."
    session.commit()
    return job
```

Define the fixtures in this integration file with this concrete seed helper, then yield sessions from the existing `fresh_postgresql_url` disposable-database fixture:

```python
def _seed_job(session: Session) -> Job:
    now = datetime.now(UTC)
    source = Source(
        name="Extraction Test Source",
        base_url="https://careers.example.test/jobs",
        adapter_key="extraction_test",
        approval_status=SourceApprovalStatus.APPROVED,
        rate_limit_policy={"requests_per_second": 1, "concurrency": 1},
        allowed_hosts=["careers.example.test"],
        terms_reviewed_at=now,
        robots_reviewed_at=now,
    )
    session.add(source)
    session.flush()
    run = CrawlRun(
        source_id=source.id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        started_at=now,
        finished_at=now,
        pages_found=1,
        items_found=1,
        adapter_version="fixture-v1",
        config_version="source-v1",
    )
    session.add(run)
    session.flush()
    snapshot = RawJobSnapshot(
        crawl_run_id=run.id,
        source_id=source.id,
        source_url="https://careers.example.test/jobs/1",
        external_id="1",
        fetched_at=now,
        http_status=200,
        content_type="text/html",
        raw_content_hash="b" * 64,
        raw_content="fixture",
        parse_status=ParseStatus.PARSED,
    )
    session.add(snapshot)
    session.flush()
    job = Job(
        source_id=source.id,
        external_id="1",
        canonical_url="https://careers.example.test/jobs/1",
        title="Backend Engineer",
        company_name="Example",
        description_text="Join the team.",
        levels=["senior"],
        first_seen_at=now,
        last_seen_at=now,
        current_snapshot_id=snapshot.id,
        job_content_hash="a" * 64,
    )
    session.add(job)
    session.commit()
    return job
```

The `job` fixture opens one seed session, calls `_seed_job`, closes it, and returns the detached job identity; the `session`, `first_session` and `second_session` fixtures open independent sessions against the same engine and load that job by ID. If the second-writer path raises an `IntegrityError`, fix the savepoint/re-read path in `persist_extraction_result` and rerun this test; do not weaken or remove the unique index.

- [ ] **Step 2: Run integration and migration gates**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_extraction_result.py tests/integration/test_postgresql_schema.py -m postgresql -q
.venv\Scripts\python -m alembic check
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: fresh upgrade, repeated upgrade, accepted-only uniqueness, rejected audit rows, rollback and concurrent winner all pass.

- [ ] **Step 3: Commit integration proof**

```powershell
git add tests/integration/test_extraction_result.py src/devradar/intelligence/extraction.py
git commit -m "test: verify extraction cache transactions"
```

### Task 6: Cập nhật contract docs, evidence và task board cục bộ

**Files:**
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/AI.md`
- Modify: `docs/OPERATIONS.md`
- Create: `docs/evidence/V3-003-extraction-result-cache.md`
- Modify: `TASK_BOARD.md` (ignored, local-only)

- [ ] **Step 1: Document the exact domain/API-free V3-003 contract**

Add to `docs/DOMAIN_MODEL.md`:

- `ExtractionResult` term with `input_type=job`, `input_ref=Job.id`, `input_hash`, extractor/schema/prompt/model/canonicalization versions, typed `output_data`, usage/cost metadata and UTC `created_at`.
- Lifecycle meaning: `accepted` may be a cache hit; `rejected` and `needs_review` are audit attempts and never cache hits.
- Cache key order exactly matching the design spec, including per-`input_ref` provenance and coalesced nullable provider versions.
- Deterministic scalar precedence and `active → missing → removed` Job lifecycle unaffected by extraction failure.

Add to `docs/AI.md`:

- deterministic extractor runs first and complete results never call provider;
- injected provider receives typed minimum input, max two transient attempts, malformed candidate is rejected without storing raw value;
- provider call is outside DB transaction and persistence re-checks accepted key;
- no production DeepSeek adapter, SDK, queue, endpoint, embedding or backfill in V3-003;
- safe metrics are result ID/status/versions/latency/tokens/estimated cost only; no raw JD/CV/prompt/output/secret.

Add to `docs/OPERATIONS.md`:

- PostgreSQL migration and integration test command uses `DEVRADAR_TEST_DATABASE_URL` and a disposable database;
- AI metrics include `ai_cache_hits_total`, accepted/rejected/needs-review counts and provider attempts;
- provider outage leaves canonical Job/raw snapshot untouched and produces `needs_review`.

- [ ] **Step 2: Write evidence file from final command output**

Create `docs/evidence/V3-003-extraction-result-cache.md` with these fixed sections and actual output copied after verification:

```markdown
# V3-003 — ExtractionResult, deterministic fallback và accepted-only cache

## Scope and non-goals

- PostgreSQL persistence, strict payload validation, deterministic-first orchestration and accepted-only cache.
- Provider callable is test/spike boundary only; no production adapter, SDK, queue, endpoint, embedding or backfill.

## Verified behavior

- complete deterministic extraction performs zero provider calls;
- accepted cache hit performs zero provider calls;
- cache identity includes input reference/hash and all extractor/schema/prompt/model/canonicalization versions;
- rejected and needs-review attempts remain auditable but never satisfy cache lookup;
- transient failure is bounded at two attempts; malformed/evidence-invalid output is rejected safely;
- deterministic levels/experience/salary/location cannot be overridden by provider candidate;
- concurrent accepted writers return one logical row; rollback leaves no half result;
- safe errors contain only bounded code/path/type and no raw JD/CV/prompt/output/secret.

## Commands and results

List the exact final outputs for the unit, PostgreSQL integration, Alembic, Ruff, format, mypy and pip checks run for this task, including skipped PostgreSQL reason when the opt-in database is unavailable.

## Boundaries not claimed

No live provider call, no external JD/CV processing, no semantic embeddings, no public extraction API and no V3 phase closeout claim.
```

Do not put test payloads containing raw secrets or real job/CV content in this evidence file.

- [ ] **Step 3: Update ignored board only after evidence exists**

Change `TASK_BOARD.md`:

```text
Ready: `V3-004` — Cài taxonomy, classification và bounded summary
`V3-003` | Cài ExtractionResult, deterministic fallback và cache | Done | `V3-002` | [Evidence](docs/evidence/V3-003-extraction-result-cache.md): unit, PostgreSQL integration, migration and static gates recorded
```

The `Done when / evidence` cell must link the new evidence and state the real test/static results. Keep `docs/ROADMAP.md` at V3 `in_progress`; this task does not satisfy the V3 `>=500` semantic/trend gate.

- [ ] **Step 4: Verify Markdown links and docs consistency**

Run the repository’s existing link/term checks (the same `rg`/PowerShell checks recorded in prior evidence) and manually verify that `ExtractionResult`, `accepted`, `needs_review`, `rejected`, cache key fields and `V3-003` use the same spelling in domain, AI, operations, evidence and task board. Do not add a new link checker dependency.

- [ ] **Step 5: Commit documentation/evidence**

```powershell
git add docs/DOMAIN_MODEL.md docs/AI.md docs/OPERATIONS.md docs/evidence/V3-003-extraction-result-cache.md
git commit -m "docs: record V3 extraction cache evidence"
```

Update `TASK_BOARD.md` locally but never stage or commit it. `git check-ignore -v TASK_BOARD.md` must report the root `.gitignore` rule, and `git status --short` must not list the board.

### Task 7: Final verification and handoff boundary

**Files:**
- Verify all files changed by Tasks 1–6; no new source file is introduced in this task.

- [ ] **Step 1: Run the narrow and full quality gates**

Run in this order:

```powershell
.venv\Scripts\python -m pytest tests/test_extraction.py -q
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_extraction_result.py tests/integration/test_postgresql_schema.py -m postgresql -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
.venv\Scripts\python -m alembic check
git diff --check
git status --short --branch
```

Record only final counts, exit status and skipped opt-in reason; never print `.env.local` or a provider key. A command is reported as passing only after its final completion output is visible.

- [ ] **Step 2: Review final diff against the design spec**

Confirm the diff has no dependency/lockfile change, provider SDK, URL-accepting endpoint, logging of raw content, cache reuse across different `input_ref`, unbounded retry, or phase-after-V3 feature. Confirm migration downgrade removes only `extraction_results` and its index.

- [ ] **Step 3: Commit only if final diff contains an uncommitted verification/doc fix**

```powershell
git diff --check
git status --short
git log -3 --oneline
```

Do not create an empty commit. Do not push: V3 remains `in_progress` until V3-004, V3-005 and V3-006 exit criteria/evidence are complete.

## Self-review checklist

- [x] Every design-spec section maps to Tasks 1–7: schema, typed payload, deterministic completeness, accepted cache, provider boundary, max-two retry, safe errors/privacy, migration, unit/integration tests and docs/evidence.
- [x] All implementation paths are exact; migration revision is fixed at `b7e3f1c4a902` and down-revision is `d9216c7fb40e`.
- [x] No future dependency or production provider is introduced.
- [x] Cache is per `input_ref`; same content hash from another Job cannot be a hit.
- [x] Failure/partial ingestion state is outside extraction persistence and cannot become Job `missing`/`removed`.
- [x] No `TBD`, `TODO`, undefined code placeholder or instruction to invent a command remains in the plan.
