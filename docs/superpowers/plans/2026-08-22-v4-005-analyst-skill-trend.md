# V4-005 Analyst Skill-Trend Responsibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement one provider-neutral analyst responsibility that converts a validated PostgreSQL skill-trend response into bounded two-endpoint facts and only publishes a typed `skill_trend` decision when exact query, metric, direction and coverage caveat gates pass.

**Architecture:** Keep `api.analytics` authoritative for cohort queries and let `agents.responsibilities` perform one direct deterministic projection into safe integer-basis-point evidence, opaque refs and `ApplicationContext`. Reuse the existing four-stage, two-attempt, zero-tool workflow and two short `AgentRun` transactions; do not add a provider, API, migration, dependency, table, tool executor or domain mutation.

**Tech Stack:** Python 3.13, Pydantic 2, FastAPI analytics DTOs, SQLAlchemy 2, PostgreSQL, pytest; existing standard-library hashing/JSON and repository tooling only.

---

## File map

- Modify `src/devradar/agents/decisions.py`: add typed trend direction and strict analyst decision invariants.
- Modify `src/devradar/agents/application.py`: add expected analyst claim/direction/caveat facts and exact publish gate.
- Modify `src/devradar/agents/responsibilities.py`: add strict trend evidence, deterministic response projection, two-endpoint analyst facts, opaque refs and builder closure.
- Modify `src/devradar/agents/workflow.py`: admit `AnalystFacts` through the existing proposal/evaluation/executor path without analyst-specific orchestration.
- Modify `src/devradar/agents/__init__.py`: export only the stable analyst projection/builder entry points.
- Modify `tests/test_agent_decisions.py`: schema, duplicate and non-publish data tests.
- Modify `tests/test_agent_application.py`: exact query/metric/direction/caveat publish-policy tests.
- Modify `tests/test_agent_responsibilities.py`: projection, basis-point, bucket, hash, redaction and fact/context closure tests.
- Modify `tests/test_agent_workflow.py`: scripted analyst publish/reject/review and failure-path reuse.
- Modify `tests/integration/test_agent_workflow.py`: real PostgreSQL analytics → projection → `AgentRun` evidence.
- Modify `README.md`: keep the current V4 task/evidence summary accurate after closeout.
- Modify `docs/AI.md` and `docs/ARCHITECTURE.md`: analyst safe-fact/application boundary and ownership.
- Modify `docs/ROADMAP.md`: mark V4-005 complete only after full evidence.
- Create `docs/evidence/V4-005-analyst-skill-trend.md`: RED→GREEN, integration, security, full-gate and untested-usefulness evidence.
- Modify local ignored `TASK_BOARD.md`: V4-005 Done and V4-006 Ready only after all gates pass.

No change is permitted in `requirements*.in`, lock files, `migrations/`, `docs/API.md`, `docs/DOMAIN_MODEL.md`, provider configuration, public routes or `AgentRun` schema.

### Task 1: Typed analyst trend decision contract

**Files:**
- Modify: `tests/test_agent_decisions.py`
- Modify: `src/devradar/agents/decisions.py`

- [ ] **Step 1: Write the failing analyst decision tests**

Change `_analyst_payload()` to use the approved slice:

```python
def _analyst_payload() -> dict[str, object]:
    metric = _ref("metric", "metric-1")
    query = _ref("aggregate_query", "query-1")
    return {
        "schemaVersion": "agent-decision-v1",
        "responsibility": "analyst",
        "decision": "publish_insight",
        "inputRefs": [query, metric],
        "evidenceRefs": [query, metric],
        "reasonCode": "evidence_supported",
        "confidence": 0.9,
        "decisionData": {
            "claimCode": "skill_trend",
            "trendDirection": "increased",
            "supportingMetricRefs": [metric],
            "caveatCodes": ["low_coverage"],
        },
    }
```

Import `AnalystTrendDirection` and replace the old typed-claim assertion with:

```python
def test_analyst_payload_uses_typed_skill_trend_contract() -> None:
    envelope = DecisionEnvelope.model_validate(_analyst_payload())

    assert isinstance(envelope.decision_data, AnalystDecisionData)
    assert envelope.decision_data.claim_code is AnalystClaimCode.SKILL_TREND
    assert envelope.decision_data.trend_direction is AnalystTrendDirection.INCREASED
    assert len(envelope.decision_data.supporting_metric_refs) == 1
```

Add strict negative coverage:

```python
@pytest.mark.parametrize(
    "decision_data",
    [
        {
            "claimCode": "skill_trend",
            "supportingMetricRefs": [_ref("metric", "metric-1")],
            "caveatCodes": [],
        },
        {
            "claimCode": "skill_trend",
            "trendDirection": "increased",
            "supportingMetricRefs": [],
            "caveatCodes": [],
        },
        {
            "claimCode": "skill_trend",
            "trendDirection": "increased",
            "supportingMetricRefs": [
                _ref("metric", "metric-1"),
                _ref("metric", "metric-1"),
            ],
            "caveatCodes": [],
        },
        {
            "claimCode": "skill_trend",
            "trendDirection": "increased",
            "supportingMetricRefs": [_ref("metric", "metric-1")],
            "caveatCodes": ["low_coverage", "low_coverage"],
        },
    ],
)
def test_analyst_publish_requires_one_direction_metric_and_unique_caveats(
    decision_data: dict[str, object],
) -> None:
    payload = _analyst_payload()
    payload["decisionData"] = decision_data

    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)


@pytest.mark.parametrize("decision", ["reject_claim", "needs_review"])
def test_analyst_non_publish_forbids_claim_data(decision: str) -> None:
    payload = _analyst_payload()
    payload["decision"] = decision
    payload["reasonCode"] = "ambiguous_claim"

    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)

    payload["decisionData"] = {}
    envelope = DecisionEnvelope.model_validate(payload)
    assert envelope.decision_data == AnalystDecisionData()


def test_analyst_rejects_duplicate_input_or_evidence_refs() -> None:
    payload = _analyst_payload()
    payload["inputRefs"] = [
        payload["inputRefs"][0],  # type: ignore[index]
        payload["inputRefs"][1],  # type: ignore[index]
        payload["inputRefs"][1],  # type: ignore[index]
    ]
    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)

    payload = _analyst_payload()
    payload["evidenceRefs"] = [
        payload["evidenceRefs"][0],  # type: ignore[index]
        payload["evidenceRefs"][1],  # type: ignore[index]
        payload["evidenceRefs"][1],  # type: ignore[index]
    ]
    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)
```

Also update `test_analyst_metric_refs_must_be_declared_evidence` to keep the intended failure isolated:

```python
payload["decisionData"] = {
    "claimCode": "skill_trend",
    "trendDirection": "increased",
    "supportingMetricRefs": [_ref("metric", "not-declared")],
    "caveatCodes": [],
}
```

- [ ] **Step 2: Run RED and verify the missing direction/strictness**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_decisions.py -q
```

Expected: collection or assertions fail because `AnalystTrendDirection`/`trend_direction` do not exist and the current analyst schema accepts missing/duplicate claim data.

- [ ] **Step 3: Implement the minimal decision contract**

Add beside the existing analyst enums:

```python
class AnalystTrendDirection(StrEnum):
    INCREASED = "increased"
    DECREASED = "decreased"
    UNCHANGED = "unchanged"
```

Replace `AnalystDecisionData` with:

```python
class AnalystDecisionData(AgentModel):
    claim_code: AnalystClaimCode | None = None
    trend_direction: AnalystTrendDirection | None = None
    supporting_metric_refs: tuple[DecisionRef, ...] = Field(default=(), max_length=16)
    caveat_codes: tuple[AnalystCaveatCode, ...] = Field(default=(), max_length=8)
```

Replace the analyst portion of `DecisionEnvelope.validate_contract()` after its type assertions with:

```python
metric_keys = {ref.key() for ref in self.decision_data.supporting_metric_refs}
if not metric_keys.issubset(evidence_keys):
    raise ValueError("analyst metric references must be evidence references")
if len(input_keys) != len(self.input_refs) or len(evidence_keys) != len(self.evidence_refs):
    raise ValueError("analyst references must be unique")
if len(metric_keys) != len(self.decision_data.supporting_metric_refs):
    raise ValueError("analyst metric references must be unique")
if len(set(self.decision_data.caveat_codes)) != len(self.decision_data.caveat_codes):
    raise ValueError("analyst caveat codes must be unique")
if self.decision is AnalystDecision.PUBLISH_INSIGHT:
    if (
        self.decision_data.claim_code is None
        or self.decision_data.trend_direction is None
        or len(self.decision_data.supporting_metric_refs) != 1
    ):
        raise ValueError("publish_insight requires claim, direction and one metric")
elif (
    self.decision_data.claim_code is not None
    or self.decision_data.trend_direction is not None
    or self.decision_data.supporting_metric_refs
    or self.decision_data.caveat_codes
):
    raise ValueError("claim data is only valid for publish_insight")
```

Add `"AnalystTrendDirection"` to `__all__`. Do not remove historical claim/caveat enum members or introduce prose fields.

- [ ] **Step 4: Run GREEN and narrow static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_decisions.py -q
.venv\Scripts\python -m ruff check src/devradar/agents/decisions.py tests/test_agent_decisions.py
.venv\Scripts\python -m mypy src/devradar/agents/decisions.py tests/test_agent_decisions.py
```

Expected: all three commands exit `0`.

- [ ] **Step 5: Commit the decision contract**

```powershell
git add src/devradar/agents/decisions.py tests/test_agent_decisions.py
git commit -m "feat: type analyst trend decisions"
```

### Task 2: Exact deterministic analyst application gate

**Files:**
- Modify: `tests/test_agent_application.py`
- Modify: `src/devradar/agents/application.py`

- [ ] **Step 1: Write the failing exact-policy tests**

Update `_analyst_envelope()` so `decisionData` is:

```python
{
    "claimCode": "skill_trend",
    "trendDirection": "increased",
    "supportingMetricRefs": [metric],
    "caveatCodes": ["low_coverage"],
}
```

Add this helper:

```python
def _analyst_context(envelope: DecisionEnvelope) -> ApplicationContext:
    metric = next(ref for ref in envelope.input_refs if ref.kind is DecisionRefKind.METRIC)
    return ApplicationContext(
        input_refs=envelope.input_refs,
        aggregate_has_denominator=True,
        aggregate_has_query_reference=True,
        supported_metric_refs=(metric,),
        expected_analyst_claim_code=AnalystClaimCode.SKILL_TREND,
        expected_analyst_trend_direction=AnalystTrendDirection.INCREASED,
        required_analyst_caveat_codes=(AnalystCaveatCode.LOW_COVERAGE,),
    )
```

Import `AnalystCaveatCode`, `AnalystClaimCode` and `AnalystTrendDirection`. Replace the current analyst publish test with:

```python
def test_analyst_publish_requires_exact_query_metric_direction_and_caveat() -> None:
    envelope = _analyst_envelope()
    accepted = apply_decision(envelope, _analyst_context(envelope))

    assert accepted.status is ApplicationStatus.ACCEPTED
    assert accepted.action is DeterministicAction.PUBLISH_INSIGHT

    invalid_payloads: list[dict[str, object]] = []
    for field, value in (
        ("claimCode", "skill_frequency"),
        ("trendDirection", "decreased"),
        ("caveatCodes", []),
        ("caveatCodes", ["low_coverage", "secondary_cohort"]),
    ):
        changed = envelope.model_dump(mode="json", by_alias=True)
        changed["decisionData"][field] = value  # type: ignore[index]
        invalid_payloads.append(changed)

    for invalid_payload in invalid_payloads:
        decision = DecisionEnvelope.model_validate(invalid_payload)
        result = apply_decision(decision, _analyst_context(envelope))
        assert result.status is ApplicationStatus.REJECTED
        assert result.action is DeterministicAction.REVIEW
        assert result.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID

    wrong_metric = DecisionRef(
        kind=DecisionRefKind.METRIC,
        id="metric-other",
        content_hash="f" * 64,
        version="skill-trend-comparison-v1",
    )
    unsupported_context = _analyst_context(envelope).model_copy(
        update={"supported_metric_refs": (wrong_metric,)}
    )
    unsupported = apply_decision(envelope, unsupported_context)
    assert unsupported.status is ApplicationStatus.REJECTED
    assert unsupported.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID
```

Add missing-query evidence and non-publish behavior:

```python
def test_analyst_publish_requires_query_ref_in_evidence() -> None:
    envelope = _analyst_envelope()
    payload = envelope.model_dump(mode="json", by_alias=True)
    payload["evidenceRefs"] = [payload["evidenceRefs"][1]]  # type: ignore[index]
    decision = DecisionEnvelope.model_validate(payload)

    result = apply_decision(decision, _analyst_context(envelope))

    assert result.status is ApplicationStatus.REJECTED
    assert result.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    ("decision", "expected_action"),
    [
        ("reject_claim", DeterministicAction.REJECT),
        ("needs_review", DeterministicAction.REVIEW),
    ],
)
def test_analyst_non_publish_remains_typed_and_accepted(
    decision: str,
    expected_action: DeterministicAction,
) -> None:
    payload = _analyst_envelope().model_dump(mode="json", by_alias=True)
    payload["decision"] = decision
    payload["reasonCode"] = "ambiguous_claim"
    payload["decisionData"] = {}
    envelope = DecisionEnvelope.model_validate(payload)

    result = apply_decision(envelope, ApplicationContext(input_refs=envelope.input_refs))

    assert result.status is ApplicationStatus.ACCEPTED
    assert result.action is expected_action
```

Update the exact `ApplicationContext.model_fields` assertion to add `expected_analyst_claim_code`, `expected_analyst_trend_direction` and `required_analyst_caveat_codes`; keep it an exact set.

- [ ] **Step 2: Run RED and verify the current subset-only gate**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_application.py -q
```

Expected: failures because expected analyst fields are absent and the current gate accepts wrong claim/direction/caveat or missing query evidence.

- [ ] **Step 3: Implement exact expected facts and publish validation**

Extend decision imports with `AnalystCaveatCode`, `AnalystClaimCode`, `AnalystTrendDirection` and `DecisionRefKind`. Add these default-deny fields to `ApplicationContext`:

```python
expected_analyst_claim_code: AnalystClaimCode | None = None
expected_analyst_trend_direction: AnalystTrendDirection | None = None
required_analyst_caveat_codes: tuple[AnalystCaveatCode, ...] = Field(
    default=(),
    max_length=3,
)
```

Replace the `PUBLISH_INSIGHT` gate in `apply_decision()` with:

```python
if envelope.decision is AnalystDecision.PUBLISH_INSIGHT:
    metric_keys = _ref_keys(envelope.decision_data.supporting_metric_refs)
    supported_keys = _ref_keys(context.supported_metric_refs)
    evidence_keys = _ref_keys(envelope.evidence_refs)
    aggregate_query_keys = {
        ref.key() for ref in context.input_refs if ref.kind is DecisionRefKind.AGGREGATE_QUERY
    }
    if (
        not context.aggregate_has_denominator
        or not context.aggregate_has_query_reference
        or len(aggregate_query_keys) != 1
        or not aggregate_query_keys.issubset(evidence_keys)
        or context.expected_analyst_claim_code is None
        or envelope.decision_data.claim_code is not context.expected_analyst_claim_code
        or context.expected_analyst_trend_direction is None
        or envelope.decision_data.trend_direction is not context.expected_analyst_trend_direction
        or len(metric_keys) != 1
        or metric_keys != supported_keys
        or not metric_keys.issubset(evidence_keys)
        or envelope.decision_data.caveat_codes != context.required_analyst_caveat_codes
    ):
        return _result(
            ApplicationStatus.REJECTED,
            DeterministicAction.REVIEW,
            ApplicationReason.AGGREGATE_EVIDENCE_INVALID,
            "aggregate_evidence_invalid",
        )
    action = DeterministicAction.PUBLISH_INSIGHT
```

Leave planner/validator branches and fallback mapping unchanged.

- [ ] **Step 4: Run GREEN plus decision regression**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_decisions.py tests/test_agent_application.py -q
.venv\Scripts\python -m ruff check src/devradar/agents/decisions.py src/devradar/agents/application.py tests/test_agent_decisions.py tests/test_agent_application.py
.venv\Scripts\python -m mypy src/devradar/agents/decisions.py src/devradar/agents/application.py tests/test_agent_decisions.py tests/test_agent_application.py
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit the application gate**

```powershell
git add src/devradar/agents/application.py tests/test_agent_application.py
git commit -m "feat: gate analyst trend publication"
```

### Task 3: Safe trend projection, evidence and analyst facts

**Files:**
- Modify: `tests/test_agent_responsibilities.py`
- Modify: `src/devradar/agents/responsibilities.py`
- Modify: `src/devradar/agents/__init__.py`

- [ ] **Step 1: Write projection and half-up RED tests**

Import analytics DTOs/enums, `date`, `JobStatus` and the new responsibility symbols. Add a helper that returns one query and a validated two-week response:

```python
def _trend_query_and_response() -> tuple[SkillTrendQuery, SkillTrendResponse]:
    query = SkillTrendQuery(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 17),
        cohort=CohortField.FIRST_SEEN_AT,
        granularity=TrendGranularity.WEEK,
        top_skills=1,
        status=JobStatus.ACTIVE,
    )
    response = SkillTrendResponse(
        data=[
            SkillTrendBucket(
                period_start=date(2026, 7, 27),
                denominator=32,
                analyzed_jobs=16,
                coverage=0.5,
                skills=[TrendSkillData(name="python", job_count=1, share=0.0312)],
            ),
            SkillTrendBucket(
                period_start=date(2026, 8, 11),
                denominator=3,
                analyzed_jobs=3,
                coverage=1.0,
                skills=[TrendSkillData(name="python", job_count=2, share=0.6667)],
            ),
        ],
        meta=SkillTrendMeta(
            cohort_size=35,
            analyzed_jobs=19,
            coverage=0.5429,
            taxonomy_version="job-taxonomy-v1",
            extraction_schema_version="job-extraction-schema-v1",
            from_date=query.from_date,
            to_date=query.to_date,
            cohort=query.cohort,
            granularity=query.granularity,
        ),
    )
    return query, response
```

Add:

```python
def test_analyst_projection_preserves_buckets_and_recomputes_integer_basis_points() -> None:
    query, response = _trend_query_and_response()

    evidence = project_analyst_trend_evidence(
        query=query,
        response=response,
        skill_name="python",
    )

    assert evidence.schema_version == "analyst-trend-evidence-v1"
    assert evidence.top_skills == 1
    assert tuple(bucket.period_start for bucket in evidence.buckets) == (
        date(2026, 7, 27),
        date(2026, 8, 11),
    )
    assert evidence.buckets[0].coverage_basis_points == 5_000
    assert evidence.buckets[0].share_basis_points == 313
    assert evidence.buckets[1].share_basis_points == 6_667
```

This explicitly proves integer half-up differs from copying the first REST float (`0.0312`).

- [ ] **Step 2: Write builder/ref/context and failure RED tests**

Add:

```python
def test_analyst_builder_selects_endpoints_and_builds_deterministic_refs() -> None:
    query, response = _trend_query_and_response()
    evidence = project_analyst_trend_evidence(
        query=query,
        response=response,
        skill_name="python",
    )

    first = build_analyst_responsibility(evidence=evidence)
    second = build_analyst_responsibility(evidence=evidence)

    assert first == second
    assert first.responsibility is Responsibility.ANALYST
    assert isinstance(first.facts, AnalystFacts)
    assert first.facts.start_bucket == evidence.buckets[0]
    assert first.facts.end_bucket == evidence.buckets[-1]
    assert first.facts.share_delta_basis_points == 6_354
    assert first.facts.trend_direction is AnalystTrendDirection.INCREASED
    assert first.facts.required_caveat_codes == (AnalystCaveatCode.LOW_COVERAGE,)
    assert first.input_refs == (
        first.facts.aggregate_query_ref,
        first.facts.trend_metric_ref,
    )
    assert first.facts.aggregate_query_ref.kind is DecisionRefKind.AGGREGATE_QUERY
    assert first.facts.trend_metric_ref.kind is DecisionRefKind.METRIC
    assert first.application_context.input_refs == first.input_refs
    assert first.application_context.supported_metric_refs == (first.facts.trend_metric_ref,)
    assert first.application_context.expected_analyst_claim_code is AnalystClaimCode.SKILL_TREND
    assert (
        first.application_context.expected_analyst_trend_direction
        is AnalystTrendDirection.INCREASED
    )
```

Add parameterized invalid cases that assert allow-listed, non-echoing `ResponsibilityBuildCode` values:

- query/response meta mismatch and missing/duplicate selected skill → `analyst_query_mismatch`;
- fewer than two, reordered or duplicate response buckets → `analyst_bucket_mismatch` or `insufficient_analyst_comparison`;
- unsafe skill/version containing newline, URL, quote or `sk-secret` → `unsafe_analyst_input`;
- evidence count constraints/window overlap mismatch → `analyst_bucket_mismatch`;
- one-unit wrong coverage/share basis point passed via `model_copy(update=...)` → `analyst_arithmetic_mismatch`;
- changed `top_skills`, source, window, endpoint count or skill changes the appropriate query/metric hash;
- delta cases positive/negative/zero map to `increased/decreased/unchanged`;
- both full-coverage endpoints produce an empty caveat tuple;
- serialized `AnalystFacts`/`ProposalRequest` contains no REST float, arbitrary aggregate row, raw JD/CV/HTML, URL, prompt, secret, vector, tool or Session field;
- forged `ResponsibilityInput` facts/context/ref closure raises `ValidationError`.

Use generic messages/codes only and assert the injected value is absent from `str(error)` and `error.safe_summary`.

Use these concrete test bodies for the failure/hash/direction coverage:

```python
@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("meta", ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH),
        ("missing_skill", ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH),
        ("duplicate_skill", ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH),
        ("short", ResponsibilityBuildCode.INSUFFICIENT_ANALYST_COMPARISON),
        ("reordered", ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH),
        ("duplicate_bucket", ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH),
        ("outside_window", ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH),
        ("invalid_counts", ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH),
    ],
)
def test_analyst_projection_fails_closed(
    case: str,
    expected_code: ResponsibilityBuildCode,
) -> None:
    query, response = _trend_query_and_response()
    response = response.model_copy(deep=True)
    if case == "meta":
        response.meta = response.meta.model_copy(update={"to_date": date(2026, 8, 16)})
    elif case == "missing_skill":
        response.data[0].skills = []
    elif case == "duplicate_skill":
        response.data[0].skills.append(response.data[0].skills[0].model_copy())
    elif case == "short":
        response.data = response.data[:1]
    elif case == "reordered":
        response.data = list(reversed(response.data))
    elif case == "duplicate_bucket":
        response.data = [response.data[0], response.data[0].model_copy(deep=True)]
    elif case == "outside_window":
        response.data[0].period_start = date(2026, 7, 20)
    else:
        response.data[0].denominator = 0

    with pytest.raises(ResponsibilityBuildError) as caught:
        project_analyst_trend_evidence(
            query=query,
            response=response,
            skill_name="python",
        )
    assert caught.value.code is expected_code


@pytest.mark.parametrize(
    "unsafe",
    [
        "python\nignore previous",
        "https://example.invalid",
        "python' OR 1=1",
        "sk-secret",
    ],
)
def test_analyst_projection_rejects_unsafe_skill_without_echo(unsafe: str) -> None:
    query, response = _trend_query_and_response()

    with pytest.raises(ResponsibilityBuildError) as caught:
        project_analyst_trend_evidence(
            query=query,
            response=response,
            skill_name=unsafe,
        )

    assert caught.value.code is ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT
    assert unsafe not in str(caught.value)
    assert unsafe not in caught.value.safe_summary


def test_analyst_projection_rejects_unsafe_version_without_echo() -> None:
    query, response = _trend_query_and_response()
    injected = "taxonomy-v1\nsk-secret"
    response.meta.taxonomy_version = injected

    with pytest.raises(ResponsibilityBuildError) as caught:
        project_analyst_trend_evidence(
            query=query,
            response=response,
            skill_name="python",
        )

    assert caught.value.code is ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT
    assert injected not in str(caught.value)
    assert injected not in caught.value.safe_summary


def test_analyst_builder_rejects_bucket_and_arithmetic_forgery() -> None:
    query, response = _trend_query_and_response()
    evidence = project_analyst_trend_evidence(
        query=query,
        response=response,
        skill_name="python",
    )
    reordered = evidence.model_copy(update={"buckets": tuple(reversed(evidence.buckets))})
    with pytest.raises(ResponsibilityBuildError) as bucket_error:
        build_analyst_responsibility(evidence=reordered)
    assert bucket_error.value.code is ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH

    forged_start = evidence.buckets[0].model_copy(
        update={"share_basis_points": evidence.buckets[0].share_basis_points + 1}
    )
    forged = evidence.model_copy(update={"buckets": (forged_start, evidence.buckets[1])})
    with pytest.raises(ResponsibilityBuildError) as arithmetic_error:
        build_analyst_responsibility(evidence=forged)
    assert arithmetic_error.value.code is ResponsibilityBuildCode.ANALYST_ARITHMETIC_MISMATCH


def _comparison_evidence(start_count: int, end_count: int) -> AnalystTrendEvidence:
    return AnalystTrendEvidence(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 17),
        cohort=CohortField.FIRST_SEEN_AT,
        granularity=TrendGranularity.WEEK,
        top_skills=1,
        status=JobStatus.ACTIVE,
        taxonomy_version="job-taxonomy-v1",
        extraction_schema_version="job-extraction-schema-v1",
        skill_name="python",
        buckets=(
            AnalystTrendBucketEvidence(
                period_start=date(2026, 7, 27),
                denominator=10,
                analyzed_jobs=10,
                coverage_basis_points=10_000,
                job_count=start_count,
                share_basis_points=start_count * 1_000,
            ),
            AnalystTrendBucketEvidence(
                period_start=date(2026, 8, 11),
                denominator=10,
                analyzed_jobs=10,
                coverage_basis_points=10_000,
                job_count=end_count,
                share_basis_points=end_count * 1_000,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("start_count", "end_count", "expected"),
    [
        (1, 2, AnalystTrendDirection.INCREASED),
        (2, 1, AnalystTrendDirection.DECREASED),
        (2, 2, AnalystTrendDirection.UNCHANGED),
    ],
)
def test_analyst_direction_and_full_coverage_caveat_are_deterministic(
    start_count: int,
    end_count: int,
    expected: AnalystTrendDirection,
) -> None:
    result = build_analyst_responsibility(evidence=_comparison_evidence(start_count, end_count))
    assert isinstance(result.facts, AnalystFacts)
    assert result.facts.trend_direction is expected
    assert result.facts.required_caveat_codes == ()


def test_analyst_refs_are_content_sensitive_and_output_is_safe() -> None:
    query, response = _trend_query_and_response()
    evidence = project_analyst_trend_evidence(
        query=query,
        response=response,
        skill_name="python",
    )
    original = build_analyst_responsibility(evidence=evidence)
    top_skills_changed = build_analyst_responsibility(
        evidence=evidence.model_copy(update={"top_skills": 2})
    )
    changed_end = evidence.buckets[-1].model_copy(
        update={
            "denominator": 3,
            "analyzed_jobs": 3,
            "coverage_basis_points": 10_000,
            "job_count": 1,
            "share_basis_points": 3_333,
        }
    )
    metric_changed = build_analyst_responsibility(
        evidence=evidence.model_copy(update={"buckets": (evidence.buckets[0], changed_end)})
    )

    assert isinstance(original.facts, AnalystFacts)
    assert isinstance(top_skills_changed.facts, AnalystFacts)
    assert isinstance(metric_changed.facts, AnalystFacts)
    assert (
        original.facts.aggregate_query_ref.content_hash
        != top_skills_changed.facts.aggregate_query_ref.content_hash
    )
    assert (
        original.facts.aggregate_query_ref.content_hash
        == metric_changed.facts.aggregate_query_ref.content_hash
    )
    assert (
        original.facts.trend_metric_ref.content_hash
        != metric_changed.facts.trend_metric_ref.content_hash
    )

    serialized = original.model_dump_json(by_alias=True)
    for forbidden in (
        "0.0312",
        "rawHtml",
        "rawCv",
        "descriptionText",
        "outputData",
        "https://",
        "prompt",
        "secret",
        "embedding",
        "toolArguments",
        "session",
    ):
        assert forbidden not in serialized

    forged = original.model_dump(mode="json", by_alias=True)
    forged["applicationContext"]["expectedAnalystTrendDirection"] = "decreased"
    with pytest.raises(ValidationError):
        ResponsibilityInput.model_validate(forged)
```

- [ ] **Step 3: Run RED and verify the analyst types/builders are absent**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_responsibilities.py -q
```

Expected: collection fails on missing analyst evidence/fact/projection/builder symbols.

- [ ] **Step 4: Add strict evidence/fact models and safe build codes**

Add these imports (merge them into existing blocks):

```python
from datetime import date, timedelta

from devradar.api.analytics import (
    CohortField,
    SkillTrendBucket,
    SkillTrendMeta,
    SkillTrendQuery,
    SkillTrendResponse,
    TrendGranularity,
    TrendSkillData,
)
from devradar.catalog.models import Job, JobStatus
```

Extend the existing decision import with `AnalystCaveatCode`, `AnalystClaimCode` and `AnalystTrendDirection`. Then add:

```python
CANONICAL_SKILL_PATTERN = r"^[a-z0-9][a-z0-9.+#-]{0,99}$"
```

Define before `ResponsibilityInput`:

```python
class AnalystTrendBucketEvidence(AgentModel):
    period_start: date
    denominator: int = Field(ge=1)
    analyzed_jobs: int = Field(ge=0)
    coverage_basis_points: int = Field(ge=0, le=10_000)
    job_count: int = Field(ge=0)
    share_basis_points: int = Field(ge=0, le=10_000)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.analyzed_jobs > self.denominator or self.job_count > self.analyzed_jobs:
            raise ValueError("analyst bucket counts are inconsistent")
        return self


class AnalystTrendEvidence(AgentModel):
    schema_version: Literal["analyst-trend-evidence-v1"] = "analyst-trend-evidence-v1"
    from_date: date
    to_date: date
    cohort: CohortField
    granularity: TrendGranularity
    top_skills: int = Field(ge=1, le=20)
    status: JobStatus
    source_id: UUID | None = None
    taxonomy_version: str = Field(min_length=1, max_length=100, pattern=_VERSION_RE.pattern)
    extraction_schema_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=_VERSION_RE.pattern,
    )
    skill_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=CANONICAL_SKILL_PATTERN,
    )
    buckets: tuple[AnalystTrendBucketEvidence, ...] = Field(
        min_length=2,
        max_length=366,
    )

    @model_validator(mode="after")
    def validate_window_and_buckets(self) -> Self:
        if self.from_date > self.to_date or (self.to_date - self.from_date).days + 1 > 366:
            raise ValueError("analyst query window is invalid")
        starts = tuple(bucket.period_start for bucket in self.buckets)
        if starts != tuple(sorted(starts)) or len(set(starts)) != len(starts):
            raise ValueError("analyst buckets must be unique and ordered")
        for start in starts:
            if self.granularity is TrendGranularity.DAY:
                overlaps = self.from_date <= start <= self.to_date
            elif self.granularity is TrendGranularity.WEEK:
                overlaps = (
                    start.weekday() == 0
                    and start.toordinal() <= self.to_date.toordinal()
                    and start.toordinal() + 6 >= self.from_date.toordinal()
                )
            else:
                if start.year == 9999 and start.month == 12:
                    month_end = date.max
                else:
                    next_month = (
                        date(start.year + 1, 1, 1)
                        if start.month == 12
                        else date(start.year, start.month + 1, 1)
                    )
                    month_end = next_month - timedelta(days=1)
                overlaps = start.day == 1 and start <= self.to_date and month_end >= self.from_date
            if not overlaps:
                raise ValueError("analyst bucket does not overlap the query window")
        return self


class AnalystFacts(AgentModel):
    schema_version: Literal["analyst-facts-v1"] = "analyst-facts-v1"
    aggregate_query_ref: DecisionRef
    trend_metric_ref: DecisionRef
    from_date: date
    to_date: date
    cohort: CohortField
    granularity: TrendGranularity
    top_skills: int = Field(ge=1, le=20)
    status: JobStatus
    source_id: UUID | None = None
    taxonomy_version: str = Field(min_length=1, max_length=100, pattern=_VERSION_RE.pattern)
    extraction_schema_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=_VERSION_RE.pattern,
    )
    skill_name: str = Field(pattern=CANONICAL_SKILL_PATTERN)
    start_bucket: AnalystTrendBucketEvidence
    end_bucket: AnalystTrendBucketEvidence
    share_delta_basis_points: int = Field(ge=-10_000, le=10_000)
    trend_direction: AnalystTrendDirection
    required_caveat_codes: tuple[AnalystCaveatCode, ...] = Field(
        default=(),
        max_length=1,
    )

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        delta = self.end_bucket.share_basis_points - self.start_bucket.share_basis_points
        direction = (
            AnalystTrendDirection.INCREASED
            if delta > 0
            else AnalystTrendDirection.DECREASED
            if delta < 0
            else AnalystTrendDirection.UNCHANGED
        )
        caveats = (
            (AnalystCaveatCode.LOW_COVERAGE,)
            if (
                self.start_bucket.coverage_basis_points < 10_000
                or self.end_bucket.coverage_basis_points < 10_000
            )
            else ()
        )
        if (
            self.aggregate_query_ref.kind is not DecisionRefKind.AGGREGATE_QUERY
            or self.trend_metric_ref.kind is not DecisionRefKind.METRIC
            or self.start_bucket.period_start >= self.end_bucket.period_start
            or self.share_delta_basis_points != delta
            or self.trend_direction is not direction
            or self.required_caveat_codes != caveats
        ):
            raise ValueError("analyst comparison facts are inconsistent")
        return self
```

Extend `ResponsibilityBuildCode` and `_SAFE_BUILD_SUMMARIES` with these exact members/messages:

```python
ANALYST_QUERY_MISMATCH = "analyst_query_mismatch"
ANALYST_BUCKET_MISMATCH = "analyst_bucket_mismatch"
ANALYST_ARITHMETIC_MISMATCH = "analyst_arithmetic_mismatch"
INSUFFICIENT_ANALYST_COMPARISON = "insufficient_analyst_comparison"
UNSAFE_ANALYST_INPUT = "unsafe_analyst_input"
```

```python
ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH: "Analyst query metadata is inconsistent.",
ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH: "Analyst trend buckets are inconsistent.",
ResponsibilityBuildCode.ANALYST_ARITHMETIC_MISMATCH: "Analyst trend arithmetic is inconsistent.",
ResponsibilityBuildCode.INSUFFICIENT_ANALYST_COMPARISON: "Analyst trend needs two periods.",
ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT: "Analyst trend input is unsafe.",
```

- [ ] **Step 5: Implement deterministic projection, hashes and builder closure**

Add these helpers after the existing safe-hash helpers:

```python
def _basis_points(
    numerator: object,
    denominator: object,
    *,
    code: ResponsibilityBuildCode,
) -> int:
    if (
        not isinstance(numerator, int)
        or isinstance(numerator, bool)
        or not isinstance(denominator, int)
        or isinstance(denominator, bool)
        or denominator <= 0
        or numerator < 0
        or numerator > denominator
    ):
        _raise(code)
    return (2 * numerator * 10_000 + denominator) // (2 * denominator)


def _analyst_direction(delta: int) -> AnalystTrendDirection:
    if delta > 0:
        return AnalystTrendDirection.INCREASED
    if delta < 0:
        return AnalystTrendDirection.DECREASED
    return AnalystTrendDirection.UNCHANGED
```

Add projection:

```python
def project_analyst_trend_evidence(
    *,
    query: SkillTrendQuery,
    response: SkillTrendResponse,
    skill_name: str,
) -> AnalystTrendEvidence:
    if (
        not isinstance(skill_name, str)
        or re.fullmatch(CANONICAL_SKILL_PATTERN, skill_name) is None
        or _VERSION_RE.fullmatch(response.meta.taxonomy_version) is None
        or _VERSION_RE.fullmatch(response.meta.extraction_schema_version) is None
    ):
        _raise(ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT)
    if (
        response.meta.from_date != query.from_date
        or response.meta.to_date != query.to_date
        or response.meta.cohort is not query.cohort
        or response.meta.granularity is not query.granularity
    ):
        _raise(ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH)
    if len(response.data) < 2:
        _raise(ResponsibilityBuildCode.INSUFFICIENT_ANALYST_COMPARISON)
    starts = tuple(bucket.period_start for bucket in response.data)
    if starts != tuple(sorted(starts)) or len(set(starts)) != len(starts):
        _raise(ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH)

    projected: list[AnalystTrendBucketEvidence] = []
    for bucket in response.data:
        matches = [item for item in bucket.skills if item.name == skill_name]
        if len(matches) != 1:
            _raise(ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH)
        selected = matches[0]
        try:
            projected.append(
                AnalystTrendBucketEvidence(
                    period_start=bucket.period_start,
                    denominator=bucket.denominator,
                    analyzed_jobs=bucket.analyzed_jobs,
                    coverage_basis_points=_basis_points(
                        bucket.analyzed_jobs,
                        bucket.denominator,
                        code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
                    ),
                    job_count=selected.job_count,
                    share_basis_points=_basis_points(
                        selected.job_count,
                        bucket.denominator,
                        code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
                    ),
                )
            )
        except ValidationError:
            raise ResponsibilityBuildError(
                ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH
            ) from None
    try:
        return AnalystTrendEvidence(
            from_date=query.from_date,
            to_date=query.to_date,
            cohort=query.cohort,
            granularity=query.granularity,
            top_skills=query.top_skills,
            status=query.status,
            source_id=query.source_id,
            taxonomy_version=response.meta.taxonomy_version,
            extraction_schema_version=response.meta.extraction_schema_version,
            skill_name=skill_name,
            buckets=tuple(projected),
        )
    except ValidationError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH) from None
```

Add builder:

```python
def build_analyst_responsibility(
    *,
    evidence: AnalystTrendEvidence,
) -> ResponsibilityInput:
    if (
        not isinstance(evidence, AnalystTrendEvidence)
        or not isinstance(evidence.skill_name, str)
        or re.fullmatch(CANONICAL_SKILL_PATTERN, evidence.skill_name) is None
        or not isinstance(evidence.taxonomy_version, str)
        or _VERSION_RE.fullmatch(evidence.taxonomy_version) is None
        or not isinstance(evidence.extraction_schema_version, str)
        or _VERSION_RE.fullmatch(evidence.extraction_schema_version) is None
    ):
        _raise(ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT)
    try:
        evidence = AnalystTrendEvidence.model_validate(
            evidence.model_dump(mode="json", by_alias=True)
        )
    except ValidationError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH) from None
    for bucket in evidence.buckets:
        if bucket.coverage_basis_points != _basis_points(
            bucket.analyzed_jobs,
            bucket.denominator,
            code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
        ) or bucket.share_basis_points != _basis_points(
            bucket.job_count,
            bucket.denominator,
            code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
        ):
            _raise(ResponsibilityBuildCode.ANALYST_ARITHMETIC_MISMATCH)

    query_payload: dict[str, object] = {
        "cohort": evidence.cohort.value,
        "extractionSchemaVersion": evidence.extraction_schema_version,
        "from": evidence.from_date.isoformat(),
        "granularity": evidence.granularity.value,
        "sourceId": str(evidence.source_id) if evidence.source_id is not None else None,
        "status": evidence.status.value,
        "taxonomyVersion": evidence.taxonomy_version,
        "to": evidence.to_date.isoformat(),
        "topSkills": evidence.top_skills,
    }
    query_hash = _safe_hash(query_payload)
    query_ref = DecisionRef(
        kind=DecisionRefKind.AGGREGATE_QUERY,
        id="skill-trend-query:" + query_hash[:32],
        content_hash=query_hash,
        version="skill-trend-query-v1",
    )
    start_bucket = evidence.buckets[0]
    end_bucket = evidence.buckets[-1]
    delta = end_bucket.share_basis_points - start_bucket.share_basis_points
    direction = _analyst_direction(delta)
    caveats = (
        (AnalystCaveatCode.LOW_COVERAGE,)
        if (
            start_bucket.coverage_basis_points < 10_000 or end_bucket.coverage_basis_points < 10_000
        )
        else ()
    )
    metric_hash = _safe_hash(
        {
            "direction": direction.value,
            "endBucket": end_bucket.model_dump(mode="json", by_alias=True),
            "queryHash": query_hash,
            "requiredCaveatCodes": [item.value for item in caveats],
            "shareDeltaBasisPoints": delta,
            "skill": evidence.skill_name,
            "startBucket": start_bucket.model_dump(mode="json", by_alias=True),
        }
    )
    metric_ref = DecisionRef(
        kind=DecisionRefKind.METRIC,
        id="skill-trend-metric:" + metric_hash[:32],
        content_hash=metric_hash,
        version="skill-trend-comparison-v1",
    )
    facts = AnalystFacts(
        aggregate_query_ref=query_ref,
        trend_metric_ref=metric_ref,
        from_date=evidence.from_date,
        to_date=evidence.to_date,
        cohort=evidence.cohort,
        granularity=evidence.granularity,
        top_skills=evidence.top_skills,
        status=evidence.status,
        source_id=evidence.source_id,
        taxonomy_version=evidence.taxonomy_version,
        extraction_schema_version=evidence.extraction_schema_version,
        skill_name=evidence.skill_name,
        start_bucket=start_bucket,
        end_bucket=end_bucket,
        share_delta_basis_points=delta,
        trend_direction=direction,
        required_caveat_codes=caveats,
    )
    input_refs = (query_ref, metric_ref)
    context = ApplicationContext(
        input_refs=input_refs,
        aggregate_has_denominator=True,
        aggregate_has_query_reference=True,
        supported_metric_refs=(metric_ref,),
        expected_analyst_claim_code=AnalystClaimCode.SKILL_TREND,
        expected_analyst_trend_direction=direction,
        required_analyst_caveat_codes=caveats,
    )
    return ResponsibilityInput(
        responsibility=Responsibility.ANALYST,
        input_refs=input_refs,
        facts=facts,
        application_context=context,
    )
```

Extend `ResponsibilityInput.facts` to `PlannerFacts | ValidatorFacts | AnalystFacts`. In `validate_closure()`, keep the existing planner context, make the validator branch an explicit `elif`, then add:

```python
elif self.responsibility is Responsibility.ANALYST:
    if not isinstance(self.facts, AnalystFacts):
        raise ValueError("analyst facts are required")
    expected_refs = (
        self.facts.aggregate_query_ref,
        self.facts.trend_metric_ref,
    )
    expected_context = ApplicationContext(
        input_refs=expected_refs,
        aggregate_has_denominator=True,
        aggregate_has_query_reference=True,
        supported_metric_refs=(self.facts.trend_metric_ref,),
        expected_analyst_claim_code=AnalystClaimCode.SKILL_TREND,
        expected_analyst_trend_direction=self.facts.trend_direction,
        required_analyst_caveat_codes=self.facts.required_caveat_codes,
    )
else:
    raise ValueError("responsibility facts do not match the responsibility")
```

Keep the existing exact `self.input_refs != expected_refs` and `self.application_context != expected_context` checks after the branches.

Export `AnalystFacts`, evidence models, projection and builder from `responsibilities.__all__` and export only `build_analyst_responsibility`/`project_analyst_trend_evidence` from `agents.__init__`.

- [ ] **Step 6: Run GREEN and focused regression/static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_responsibilities.py tests/test_agent_application.py tests/test_agent_decisions.py -q
.venv\Scripts\python -m ruff check src/devradar/agents tests/test_agent_responsibilities.py tests/test_agent_application.py tests/test_agent_decisions.py
.venv\Scripts\python -m mypy src/devradar/agents tests/test_agent_responsibilities.py tests/test_agent_application.py tests/test_agent_decisions.py
```

Expected: all commands exit `0`; no test touches PostgreSQL or network.

- [ ] **Step 7: Commit the safe analyst facts**

```powershell
git add src/devradar/agents/responsibilities.py src/devradar/agents/__init__.py tests/test_agent_responsibilities.py
git commit -m "feat: build safe analyst trend facts"
```

### Task 4: Reuse the bounded direct workflow for analyst proposals

**Files:**
- Modify: `tests/test_agent_workflow.py`
- Modify: `src/devradar/agents/workflow.py`

- [ ] **Step 1: Write analyst workflow RED helpers and success outcomes**

Add an analyst input helper using only safe evidence:

```python
def _analyst_input() -> ResponsibilityInput:
    evidence = AnalystTrendEvidence(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 17),
        cohort=CohortField.FIRST_SEEN_AT,
        granularity=TrendGranularity.WEEK,
        top_skills=1,
        status=JobStatus.ACTIVE,
        taxonomy_version="job-taxonomy-v1",
        extraction_schema_version="job-extraction-schema-v1",
        skill_name="python",
        buckets=(
            AnalystTrendBucketEvidence(
                period_start=date(2026, 7, 27),
                denominator=2,
                analyzed_jobs=1,
                coverage_basis_points=5_000,
                job_count=1,
                share_basis_points=5_000,
            ),
            AnalystTrendBucketEvidence(
                period_start=date(2026, 8, 11),
                denominator=2,
                analyzed_jobs=2,
                coverage_basis_points=10_000,
                job_count=2,
                share_basis_points=10_000,
            ),
        ),
    )
    return build_analyst_responsibility(evidence=evidence)
```

Add a candidate helper:

```python
def _analyst_candidate(
    responsibility_input: ResponsibilityInput,
    *,
    decision: str = "publish_insight",
    direction: str = "increased",
    caveats: list[str] | None = None,
) -> dict[str, object]:
    refs = [ref.model_dump(mode="json", by_alias=True) for ref in responsibility_input.input_refs]
    if decision == "publish_insight":
        decision_data: dict[str, object] = {
            "claimCode": "skill_trend",
            "trendDirection": direction,
            "supportingMetricRefs": [refs[1]],
            "caveatCodes": ["low_coverage"] if caveats is None else caveats,
        }
        reason_code = "evidence_supported"
    else:
        decision_data = {}
        reason_code = "ambiguous_claim"
    return {
        "schemaVersion": "agent-decision-v1",
        "responsibility": "analyst",
        "decision": decision,
        "inputRefs": refs,
        "evidenceRefs": refs,
        "reasonCode": reason_code,
        "confidence": 0.9,
        "decisionData": decision_data,
    }
```

Import `date`, analytics enums, `JobStatus` and analyst responsibility symbols. Add:

```python
@pytest.mark.parametrize(
    ("decision", "expected_status", "expected_action"),
    [
        ("publish_insight", AgentRunStatus.SUCCEEDED, DeterministicAction.PUBLISH_INSIGHT),
        ("reject_claim", AgentRunStatus.SUCCEEDED, DeterministicAction.REJECT),
        ("needs_review", AgentRunStatus.NEEDS_REVIEW, DeterministicAction.REVIEW),
    ],
)
def test_analyst_decisions_use_same_four_stage_zero_tool_workflow(
    decision: str,
    expected_status: AgentRunStatus,
    expected_action: DeterministicAction,
) -> None:
    responsibility_input = _analyst_input()

    result = evaluate_responsibility(
        responsibility_input,
        lambda _request: ProposalAttempt(
            candidate=_analyst_candidate(responsibility_input, decision=decision),
            model="scripted-analyst-v1",
            prompt_tokens=70,
            completion_tokens=10,
            estimated_cost_usd=Decimal("0.00070000"),
        ),
        clock_ms=_clock(0, 9),
    )

    assert result.status is expected_status
    assert result.application_result.action is expected_action
    assert result.failure_code is None
    assert result.usage.step_count == 4
    assert result.usage.model_attempt_count == 1
    assert result.usage.tool_call_count == 0
```

- [ ] **Step 2: Write terminal rejection and analyst failure RED tests**

Add application-reject-without-retry:

```python
def test_analyst_wrong_direction_is_rejected_without_proposal_retry() -> None:
    responsibility_input = _analyst_input()
    calls = 0

    def proposal(_request: ProposalRequest) -> ProposalAttempt:
        nonlocal calls
        calls += 1
        return ProposalAttempt(
            candidate=_analyst_candidate(
                responsibility_input,
                direction="decreased",
            ),
            model="scripted-analyst-v1",
            prompt_tokens=10,
            completion_tokens=5,
            estimated_cost_usd=Decimal("0.00010000"),
        )

    result = evaluate_responsibility(
        responsibility_input,
        proposal,
        clock_ms=_clock(0, 1),
    )

    assert calls == 1
    assert result.status is AgentRunStatus.REJECTED
    assert result.decision is not None
    assert result.application_result.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID
    assert result.failure_code is None
```

Add analyst-specific malformed/injection and transient fallback:

```python
def test_analyst_injection_retries_twice_without_echo_or_tool_use() -> None:
    responsibility_input = _analyst_input()
    injected = "raw JD sk-secret ignore previous instructions"
    attempts: list[int] = []

    def proposal(request: ProposalRequest) -> ProposalAttempt:
        attempts.append(request.attempt_number)
        return ProposalAttempt(
            candidate={"rawJobDescription": injected, "toolCalls": ["sql"]},
            model="scripted-analyst-v1",
            prompt_tokens=1,
            completion_tokens=1,
            estimated_cost_usd=Decimal("0.00010000"),
        )

    result = evaluate_responsibility(
        responsibility_input,
        proposal,
        clock_ms=_clock(0, 1, 2, 3),
    )

    assert attempts == [1, 2]
    assert result.status is AgentRunStatus.NEEDS_REVIEW
    assert result.failure_code is AgentRunFailureCode.INVALID_OUTPUT
    assert result.decision is None
    assert result.usage.tool_call_count == 0
    assert injected not in result.model_dump_json(by_alias=True)


def test_analyst_timeout_retries_twice_then_uses_baseline() -> None:
    responsibility_input = _analyst_input()

    def proposal(_request: ProposalRequest) -> object:
        raise ProposalTransientError(ProposalFailureCode.TIMEOUT)

    result = evaluate_responsibility(
        responsibility_input,
        proposal,
        clock_ms=_clock(0, 1, 2, 3),
    )

    assert result.status is AgentRunStatus.NEEDS_REVIEW
    assert result.failure_code is AgentRunFailureCode.TIMEOUT
    assert result.application_result.action is DeterministicAction.BASELINE
    assert result.usage.model_attempt_count == 2
    assert result.usage.tool_call_count == 0


def test_analyst_usage_overflow_discards_unaccepted_delta() -> None:
    responsibility_input = _analyst_input()
    result = evaluate_responsibility(
        responsibility_input,
        lambda _request: ProposalAttempt(
            candidate=_analyst_candidate(responsibility_input),
            model="scripted-analyst-v1",
            prompt_tokens=8_001,
            completion_tokens=0,
            estimated_cost_usd=Decimal("0"),
        ),
        clock_ms=_clock(0, 1),
    )

    assert result.status is AgentRunStatus.NEEDS_REVIEW
    assert result.failure_code is AgentRunFailureCode.LIMIT_EXCEEDED
    assert result.decision is None
    assert result.usage.model_attempt_count == 0
    assert result.usage.prompt_tokens == 0
    assert result.usage.tool_call_count == 0


def test_analyst_unexpected_error_fails_without_echo() -> None:
    responsibility_input = _analyst_input()
    injected = "raw aggregate sk-secret"

    def proposal(_request: ProposalRequest) -> object:
        raise RuntimeError(injected)

    result = evaluate_responsibility(
        responsibility_input,
        proposal,
        clock_ms=_clock(0, 1),
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.failure_code is AgentRunFailureCode.INTERNAL_ERROR
    assert result.decision is None
    assert injected not in result.model_dump_json(by_alias=True)
```

Keep existing generic tests as the authoritative exact accepted token/cost/latency boundaries; the evaluator must not add a responsibility-specific limit branch.

- [ ] **Step 3: Run RED and verify `ProposalRequest` rejects analyst facts**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_workflow.py -q
```

Expected: analyst cases fail because `ProposalRequest.facts`/closure currently only admit planner and validator facts.

- [ ] **Step 4: Extend only the typed workflow union/closure**

Import `AnalystFacts` in `workflow.py`. Change:

```python
facts: PlannerFacts | ValidatorFacts | AnalystFacts
```

Replace `ProposalRequest.validate_closure()` branching with explicit planner, validator and analyst branches:

```python
if self.responsibility is Responsibility.PLANNER:
    if not isinstance(self.facts, PlannerFacts):
        raise ValueError("planner facts are required")
    expected_refs = (self.facts.source_ref,)
    if self.facts.crawl_run_ref is not None:
        expected_refs += (self.facts.crawl_run_ref,)
elif self.responsibility is Responsibility.VALIDATOR:
    if not isinstance(self.facts, ValidatorFacts):
        raise ValueError("validator facts are required")
    expected_refs = (self.facts.extraction_result_ref,)
    if self.facts.raw_snapshot_ref is not None:
        expected_refs += (self.facts.raw_snapshot_ref,)
elif self.responsibility is Responsibility.ANALYST:
    if not isinstance(self.facts, AnalystFacts):
        raise ValueError("analyst facts are required")
    expected_refs = (
        self.facts.aggregate_query_ref,
        self.facts.trend_metric_ref,
    )
else:
    raise ValueError("responsibility is not implemented by this workflow")
```

Keep the existing exact tuple comparison after this branch. Do not change evaluator/executor stages, attempts, limits, transaction handling, fallback or persistence.

- [ ] **Step 5: Run GREEN plus full agent unit regression**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_decisions.py tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/test_agent_run_state.py -q
.venv\Scripts\python -m ruff check src/devradar/agents tests/test_agent_decisions.py tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py
.venv\Scripts\python -m mypy src/devradar/agents tests/test_agent_decisions.py tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit direct analyst workflow reuse**

```powershell
git add src/devradar/agents/workflow.py tests/test_agent_workflow.py
git commit -m "feat: run bounded analyst trend workflow"
```

### Task 5: Real PostgreSQL analytics-to-AgentRun integration

**Files:**
- Modify: `tests/integration/test_agent_workflow.py`

- [ ] **Step 1: Extend the real-row fixture with two trend buckets**

Import `date`, `SkillTrendQuery`, `TrendGranularity`, `list_skill_trends`, `AnalystFacts`, `build_analyst_responsibility` and `project_analyst_trend_evidence`.

Inside `responsibility_inputs`, after creating planner/validator rows, add four active Jobs for the same source:

```python
trend_dates = (
    datetime(2026, 8, 3, tzinfo=UTC),
    datetime(2026, 8, 4, tzinfo=UTC),
    datetime(2026, 8, 10, tzinfo=UTC),
    datetime(2026, 8, 11, tzinfo=UTC),
)
trend_jobs: list[Job] = []
for index, first_seen_at in enumerate(trend_dates, start=1):
    snapshot = RawJobSnapshot(
        crawl_run_id=run.id,
        source_id=source.id,
        source_url="https://careers.example.test/jobs/trend-" + str(index),
        external_id="trend-" + str(index),
        fetched_at=now,
        http_status=200,
        content_type="text/html",
        raw_content_hash=format(index + 4, "x") * 64,
        raw_content=RAW_SNAPSHOT_CONTENT,
        parse_status=ParseStatus.PARSED,
    )
    session.add(snapshot)
    session.flush()
    job = Job(
        source_id=source.id,
        external_id="trend-" + str(index),
        canonical_url="https://careers.example.test/jobs/trend-" + str(index),
        title="Trend Backend Engineer",
        company_name="Example",
        description_text=JOB_DESCRIPTION,
        levels=["senior"],
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
        current_snapshot_id=snapshot.id,
        job_content_hash=format(index, "x") * 64,
    )
    session.add(job)
    session.flush()
    trend_jobs.append(job)

for job in (trend_jobs[0], trend_jobs[2], trend_jobs[3]):
    session.add(
        ExtractionResult(
            input_type=ExtractionInputType.JOB.value,
            input_ref=job.id,
            input_hash=job.job_content_hash,
            extractor_type=ExtractionType.RULE.value,
            extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
            schema_version=EXTRACTION_SCHEMA_VERSION,
            prompt_version=None,
            model=None,
            canonicalization_version=CANONICALIZATION_VERSION,
            output_data=_payload(),
            validation_status=ExtractionValidationStatus.ACCEPTED.value,
            validation_errors=None,
        )
    )
session.flush()

trend_query = SkillTrendQuery(
    from_date=date(2026, 8, 1),
    to_date=date(2026, 8, 16),
    granularity=TrendGranularity.WEEK,
    top_skills=1,
    source_id=source.id,
)
trend_response = list_skill_trends(filters=trend_query, session=session)
analyst_input = build_analyst_responsibility(
    evidence=project_analyst_trend_evidence(
        query=trend_query,
        response=trend_response,
        skill_name="python",
    )
)
```

Return `(planner_input, validator_input, analyst_input)` and update the fixture annotation and consumers accordingly. Update the committed-running parameterization from `[0, 1]` to `[0, 1, 2]`.

- [ ] **Step 2: Extend the scripted candidate helper and write the integration assertions**

In `_candidate()`, keep the planner branch, change the current unconditional validator return into `if responsibility_input.responsibility is Responsibility.VALIDATOR:`, and add this analyst tail after it:

```python
facts = responsibility_input.facts
assert isinstance(facts, AnalystFacts)
return {
    "schemaVersion": "agent-decision-v1",
    "responsibility": "analyst",
    "decision": "publish_insight",
    "inputRefs": refs,
    "evidenceRefs": refs,
    "reasonCode": "evidence_supported",
    "confidence": 0.9,
    "decisionData": {
        "claimCode": "skill_trend",
        "trendDirection": facts.trend_direction.value,
        "supportingMetricRefs": [refs[1]],
        "caveatCodes": [item.value for item in facts.required_caveat_codes],
    },
}
```

Update `test_real_rows_build_safe_planner_and_validator_provenance` to include the analyst input and assert:

```python
assert analyst_input.responsibility is Responsibility.ANALYST
assert isinstance(analyst_input.facts, AnalystFacts)
assert analyst_input.facts.start_bucket.denominator == 2
assert analyst_input.facts.start_bucket.coverage_basis_points == 5_000
assert analyst_input.facts.start_bucket.share_basis_points == 5_000
assert analyst_input.facts.end_bucket.coverage_basis_points == 10_000
assert analyst_input.facts.end_bucket.share_basis_points == 10_000
assert analyst_input.facts.required_caveat_codes == (AnalystCaveatCode.LOW_COVERAGE,)
```

Include analyst `ProposalRequest` serialization in the existing raw-content redaction loop.

- [ ] **Step 3: Write persisted publish and application-reject evidence**

The existing parameterized executor test with index `2` must prove transaction one exposes a committed `running` row and transaction two stores exact usage, decision and zero tools. Add an analyst-specific persisted assertion:

```python
@pytest.mark.postgresql
def test_analyst_application_reject_persists_decision_without_publish(
    workflow_session_factory: sessionmaker[Session],
    responsibility_inputs: tuple[
        ResponsibilityInput,
        ResponsibilityInput,
        ResponsibilityInput,
    ],
) -> None:
    analyst_input = responsibility_inputs[2]
    candidate = _candidate(analyst_input)
    candidate["decisionData"]["trendDirection"] = "decreased"  # type: ignore[index]

    outcome = execute_responsibility(
        workflow_session_factory,
        responsibility_input=analyst_input,
        proposal=lambda _request: ProposalAttempt(
            candidate=candidate,
            model="scripted-integration-v1",
            prompt_tokens=100,
            completion_tokens=20,
            estimated_cost_usd=Decimal("0.00100000"),
        ),
        correlation_id="f" * 32,
        clock_ms=_clock(0, 1),
    )

    assert outcome.status is AgentRunStatus.REJECTED
    assert outcome.application_result.action is DeterministicAction.REVIEW
    with workflow_session_factory() as session:
        stored = session.get(AgentRun, outcome.run_id)
        assert stored is not None
        assert stored.status == AgentRunStatus.REJECTED.value
        assert stored.decision_data is not None
        assert stored.decision_data["decisionData"]["trendDirection"] == "decreased"
        assert stored.tool_call_count == 0
```

Import `AnalystCaveatCode` and `DeterministicAction`. Change the existing injection test to execute `responsibility_inputs[2]` so raw/prompt/tool candidate rejection is proven on the analyst slice. Keep finalize-failure/global-active-slot coverage unchanged because executor transaction semantics are shared.

- [ ] **Step 4: Run focused PostgreSQL analyst integration**

```powershell
docker compose --env-file .env.example up database --wait
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_workflow.py -q -k "analyst or real_rows"
    if ($LASTEXITCODE -ne 0) { throw "V4-005 focused PostgreSQL integration failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: focused analyst/real-row cases pass without skips. RED evidence already comes from Tasks 1–4 before production contract/workflow implementation; this task adds real-database verification for that implemented slice.

- [ ] **Step 5: Run the complete workflow integration and static gates**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_workflow.py -q
    if ($LASTEXITCODE -ne 0) { throw "V4-005 PostgreSQL integration gate failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
.venv\Scripts\python -m ruff check tests/integration/test_agent_workflow.py
.venv\Scripts\python -m mypy tests/integration/test_agent_workflow.py
```

Expected: integration file passes without skips and both static commands exit `0`.

- [ ] **Step 6: Commit real analytics integration**

```powershell
git add tests/integration/test_agent_workflow.py
git commit -m "test: verify analyst trend postgres workflow"
```

### Task 6: Documentation, full verification and V4-005 closeout

**Files:**
- Modify: `README.md`
- Modify: `docs/AI.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/evidence/V4-005-analyst-skill-trend.md`
- Modify local ignored: `TASK_BOARD.md`

- [ ] **Step 1: Run targeted unit and PostgreSQL gates before status changes**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_decisions.py tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/test_agent_run_state.py -q
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_workflow.py -q
    if ($LASTEXITCODE -ne 0) { throw "V4-005 targeted PostgreSQL gate failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: both commands finish with zero failures; PostgreSQL output must not be skipped.

- [ ] **Step 2: Run full default/PostgreSQL and static/dependency gates**

```powershell
.venv\Scripts\python -m pytest
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "V4-005 full PostgreSQL gate failed" }
    .venv\Scripts\python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed" }
    .venv\Scripts\python -m alembic check
    if ($LASTEXITCODE -ne 0) { throw "Alembic check failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
docker compose --env-file .env.example --profile crawler config --quiet
```

Expected: every command exits `0`. Default PostgreSQL tests may be skipped only in the first command; the second full run must execute them.

- [ ] **Step 3: Run scope, security and Markdown gates**

Resolve the implementation base as the commit that introduced this plan:

```powershell
$baseCommit = git log -1 --format=%H -- docs/superpowers/plans/2026-08-22-v4-005-analyst-skill-trend.md
git diff $baseCommit -- requirements.in requirements-dev.in requirements.lock requirements-dev.lock
git diff $baseCommit -- migrations
git diff $baseCommit -- docs/API.md docs/DOMAIN_MODEL.md
git diff --check
git check-ignore TASK_BOARD.md .env.local
git ls-files --error-unmatch TASK_BOARD.md 2>$null
if ($LASTEXITCODE -eq 0) {
    throw "TASK_BOARD.md must remain untracked"
}
$global:LASTEXITCODE = 0
```

Expected: dependency, migration, API and domain-model diffs are empty; `git diff --check` exits `0`; ignore checks print rules; `git ls-files --error-unmatch TASK_BOARD.md` fails because the board remains untracked.

Run:

```powershell
rg -n -i "raw_content|raw cv|description_text|output_data|prompt|provider_body|api[_ -]?key|secret|tool_arguments|embedding|session|commit\(|rollback\(" src/devradar/agents tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/integration/test_agent_workflow.py
```

Review every hit. Allowed hits are imports/local deterministic reads, negative fixtures/assertions and documentation strings; no raw content, secret, Session, prompt/provider body or tool handle may appear in `AnalystFacts`, `ProposalRequest`, `DecisionEnvelope`, `AgentExecutionOutcome` or stored decision JSON.

Use the fail-fast repository Markdown scanner:

```powershell
$ErrorActionPreference = 'Stop'
$tracked = @(git ls-files '*.md')
$untracked = @(git ls-files --others --exclude-standard '*.md')
$files = @($tracked + $untracked | Sort-Object -Unique)
$invalid = @()
$linkCount = 0
foreach ($file in $files) {
    $text = Get-Content -Raw -LiteralPath $file
    foreach ($match in [regex]::Matches($text, '\[[^\]]*\]\((?<target>[^)]+)\)')) {
        $target = $match.Groups['target'].Value.Trim()
        if ($target.StartsWith('<') -and $target.EndsWith('>')) {
            $target = $target.Substring(1, $target.Length - 2)
        }
        if ($target -match '^(https?://|mailto:|#)') { continue }
        $pathPart = ($target -split '#', 2)[0]
        $pathPart = ($pathPart -split '\?', 2)[0]
        if ([string]::IsNullOrWhiteSpace($pathPart)) { continue }
        $linkCount += 1
        $decoded = [Uri]::UnescapeDataString($pathPart)
        $base = Split-Path -Parent $file
        if ([string]::IsNullOrEmpty($base)) { $base = '.' }
        $resolved = Join-Path $base $decoded
        if (-not (Test-Path -LiteralPath $resolved)) {
            $invalid += "${file}: ${target}"
        }
    }
}
Write-Output "MARKDOWN_FILES=$($files.Count) INTERNAL_LINKS=$linkCount INVALID=$($invalid.Count)"
$invalid
if ($invalid.Count -gt 0) { exit 1 }
```

Record exact file/link counts in evidence.

- [ ] **Step 4: Update authoritative docs and local board from actual evidence**

In `docs/AI.md` document:

- `analyst-trend-evidence-v1` projects one validated top skill across all supplied buckets and recomputes integer half-up basis points from counts;
- `analyst-facts-v1` exposes only first/last bucket, exact query/metric refs, deterministic direction and exact low-coverage caveat;
- publish is default-deny on exact claim/query/metric/direction/caveat;
- no raw Job/JD/CV/ExtractionResult, float aggregate, query handle, Session, SQL, provider or tool crosses the proposal boundary;
- scripted workflow proves contract correctness only; V4-006 owns keep/delete usefulness.

In `docs/ARCHITECTURE.md` update module ownership and V4 flow to show `existing analytics → explicit safe projection → direct analyst proposal → deterministic application → existing two-transaction AgentRun`. Keep `api.analytics` authoritative and unchanged.

Create `docs/evidence/V4-005-analyst-skill-trend.md` with actual:

- RED failure and GREEN targeted/full counts;
- half-up tie case and positive/negative/unchanged hashes/directions;
- query/meta/bucket/arithmetic/unsafe-input failure codes and no-echo assertions;
- exact publish/reject/review/application-reject outcomes;
- real PostgreSQL denominator/coverage/endpoints, committed-running visibility, persisted refs/decision/usage and zero tools;
- dependency/migration/API/domain/Markdown/security scans;
- boundaries: no live provider, no JD/CV/raw HTML sent externally, no public insight, no usefulness improvement claim.

Only after every gate above passes:

- update `README.md` to summarize V4-005 evidence and identify V4-006 as the next task;
- update `docs/ROADMAP.md` to V4-005 complete with evidence link, V4-006 Ready and V4 still `in_progress`;
- update ignored `TASK_BOARD.md` to V4-005 Done and V4-006 Ready;
- do not mark V4 complete or start V5.

- [ ] **Step 5: Re-run doc/diff checks and review the complete implementation**

```powershell
git status --short --branch
git diff --check
$baseCommit = git log -1 --format=%H -- docs/superpowers/plans/2026-08-22-v4-005-analyst-skill-trend.md
git diff --stat $baseCommit
git diff $baseCommit -- src/devradar/agents tests/test_agent_decisions.py tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/integration/test_agent_workflow.py README.md docs/AI.md docs/ARCHITECTURE.md docs/ROADMAP.md docs/evidence/V4-005-analyst-skill-trend.md
git diff $baseCommit -- requirements.in requirements-dev.in requirements.lock requirements-dev.lock migrations docs/API.md docs/DOMAIN_MODEL.md
```

Confirm the final scope contains no dependency, migration, API, domain-model, provider, tool executor, LangGraph, prose insight, new persistence, domain mutation or unrelated cleanup. Re-run the Markdown scanner after doc edits and require `INVALID=0`.

- [ ] **Step 6: Commit closeout and preserve the phase push gate**

```powershell
docker compose --env-file .env.example down
git add README.md docs/AI.md docs/ARCHITECTURE.md docs/ROADMAP.md docs/evidence/V4-005-analyst-skill-trend.md
git commit -m "docs: close v4-005 analyst skill trend"
git status --short --branch
git log -6 --oneline --decorate
```

Do not stage `TASK_BOARD.md` or `.env.local`. Do not push: repository policy defers push until V4-006 closes the complete V4 phase.
