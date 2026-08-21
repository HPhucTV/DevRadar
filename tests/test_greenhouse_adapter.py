from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from devradar.ingestion.adapters.greenhouse import (
    GreenhouseAdapterError,
    GreenhouseJobBoardAdapter,
)
from devradar.ingestion.contracts import (
    FetchResult,
    ListingRef,
    ParsedJob,
    ParseFailure,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.models import SourceApprovalStatus
from devradar.ingestion.safe_http import FetchError, FetchErrorCode
from devradar.ingestion.source_registry import (
    NAVER_VIETNAM_GREENHOUSE,
    AdapterRegistry,
    PolicyScope,
    SourceConfig,
)

FIXTURES = Path(__file__).parent / "fixtures" / "greenhouse"
LIST_URL = "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs?content=true"


class FakeHttpFetch:
    def __init__(self, results: Iterable[FetchResult | BaseException]) -> None:
        self._results = iter(results)
        self.calls: list[str] = []

    def __call__(self, url: str, fetch_policy: object) -> FetchResult:
        del fetch_policy
        self.calls.append(url)
        result = next(self._results)
        if isinstance(result, BaseException):
            raise result
        return result


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _fetch_result(name: str) -> FetchResult:
    payload = _fixture_bytes(name)
    return FetchResult(
        final_url=LIST_URL,
        fetched_at=datetime(2026, 8, 21, 4, 5, 6, tzinfo=UTC),
        http_status=200,
        content_type="application/json; charset=utf-8",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


def _run_context(*, source: SourceConfig = NAVER_VIETNAM_GREENHOUSE) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        source=source,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="greenhouse-fixture-test",
    )


def _snapshot(name: str, external_id: str) -> RawSnapshot:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return RawSnapshot(
        snapshot_id=uuid4(),
        source_key=NAVER_VIETNAM_GREENHOUSE.source_key,
        external_id=external_id,
        source_url=LIST_URL,
        fetched_at=datetime(2026, 8, 21, 4, 5, 6, tzinfo=UTC),
        content_type="application/json; charset=utf-8",
        raw_content=raw,
        raw_content_hash=sha256(raw.encode("utf-8")).hexdigest(),
    )


def test_discover_uses_one_bounded_content_list_and_fetch_reuses_raw_response() -> None:
    result = _fetch_result("jobs_happy.json")
    http_fetch = FakeHttpFetch((result,))
    adapter = GreenhouseJobBoardAdapter(http_fetch=http_fetch)

    listings = adapter.discover(_run_context())

    assert [listing.external_id for listing in listings] == ["1001", "1002"]
    assert listings[0].canonical_url == ("https://job-boards.greenhouse.io/navervietnam/jobs/1001")
    assert listings[0].metadata["internal_job_id"] == 9001
    assert http_fetch.calls == [LIST_URL]
    assert adapter.fetch(listings[0], NAVER_VIETNAM_GREENHOUSE.fetch_policy) is result
    assert adapter.fetch(listings[1], NAVER_VIETNAM_GREENHOUSE.fetch_policy) is result
    assert http_fetch.calls == [LIST_URL]

    forged = ListingRef(
        external_id="9999",
        canonical_url="https://job-boards.greenhouse.io/navervietnam/jobs/9999",
    )
    with pytest.raises(GreenhouseAdapterError) as captured:
        adapter.fetch(forged, NAVER_VIETNAM_GREENHOUSE.fetch_policy)
    assert captured.value.code == "listing_not_discovered"


@pytest.mark.parametrize("fixture", ["jobs_happy.json", "job_detail_happy.json"])
def test_parse_list_or_detail_extracts_safe_deterministic_job(fixture: str) -> None:
    adapter = GreenhouseJobBoardAdapter(http_fetch=FakeHttpFetch(()))

    parsed = adapter.parse(_snapshot(fixture, "1001"))

    assert isinstance(parsed, ParsedJob)
    assert parsed.raw.external_id == "1001"
    assert parsed.raw.canonical_url.endswith("/navervietnam/jobs/1001")
    assert parsed.raw.title == "Backend Engineer"
    assert parsed.raw.company_name == "NAVER Vietnam"
    assert parsed.raw.location == "Ho Chi Minh City, Vietnam"
    assert parsed.raw.description == "Build & own backend services.\nPython\nPostgreSQL"
    assert "unsafe" not in parsed.raw.description
    assert parsed.raw.source_fields["departments"] == "Engineering"
    assert parsed.raw.source_fields["offices"] == "Ho Chi Minh City"
    assert parsed.normalized_candidates.location_city == "Ho Chi Minh City"
    assert parsed.normalized_candidates.posted_at is None
    assert parsed.parser_version == "greenhouse-job-board-v1"
    assert "updated_at_not_used_as_posted_at" in parsed.warnings
    assert {evidence.field_name for evidence in parsed.evidence} >= {
        "external_id",
        "canonical_url",
        "title",
        "company_name",
        "description",
        "location",
    }


def test_missing_optional_department_and_metadata_remain_nullable() -> None:
    parsed = GreenhouseJobBoardAdapter(http_fetch=FakeHttpFetch(())).parse(
        _snapshot("jobs_happy.json", "1002")
    )

    assert isinstance(parsed, ParsedJob)
    assert parsed.raw.source_fields["internal_job_id"] is None
    assert parsed.raw.source_fields["requisition_id"] is None
    assert parsed.raw.source_fields["departments"] is None
    assert parsed.raw.source_fields["offices"] is None
    assert parsed.normalized_candidates.location_city == "Hanoi"


@pytest.mark.parametrize(
    ("fixture", "expected_code"),
    [
        ("jobs_empty.json", "empty_result"),
        ("jobs_meta_mismatch.json", "coverage_mismatch"),
        ("jobs_duplicate_conflict.json", "duplicate_job_id"),
        ("jobs_layout_regression.json", "layout_regression"),
        ("jobs_malformed.json", "malformed_json"),
    ],
)
def test_discover_rejects_incomplete_or_regressed_fixture(
    fixture: str,
    expected_code: str,
) -> None:
    adapter = GreenhouseJobBoardAdapter(http_fetch=FakeHttpFetch((_fetch_result(fixture),)))

    with pytest.raises(GreenhouseAdapterError) as captured:
        adapter.discover(_run_context())

    assert captured.value.code == expected_code
    assert "navervietnam" not in captured.value.safe_summary


def test_timeout_propagates_safe_fetch_taxonomy_and_invalidates_previous_batch() -> None:
    timeout = FetchError(
        FetchErrorCode.NETWORK_TIMEOUT,
        "Approved source request timed out.",
        retryable=True,
    )
    http_fetch = FakeHttpFetch((_fetch_result("jobs_happy.json"), timeout))
    adapter = GreenhouseJobBoardAdapter(http_fetch=http_fetch)
    listing = adapter.discover(_run_context())[0]

    with pytest.raises(FetchError) as captured:
        adapter.discover(_run_context())
    assert captured.value.code is FetchErrorCode.NETWORK_TIMEOUT

    with pytest.raises(GreenhouseAdapterError) as stale:
        adapter.fetch(listing, NAVER_VIETNAM_GREENHOUSE.fetch_policy)
    assert stale.value.code == "listing_not_discovered"


def test_wrong_run_config_is_rejected_before_http() -> None:
    http_fetch = FakeHttpFetch(())
    adapter = GreenhouseJobBoardAdapter(http_fetch=http_fetch)
    mismatched = replace(NAVER_VIETNAM_GREENHOUSE, config_version="unexpected")

    with pytest.raises(GreenhouseAdapterError) as captured:
        adapter.discover(_run_context(source=mismatched))

    assert captured.value.code == "source_config_mismatch"
    assert http_fetch.calls == []


def test_candidate_config_cannot_construct_adapter_or_enter_registry() -> None:
    candidate = replace(
        NAVER_VIETNAM_GREENHOUSE,
        approval_status=SourceApprovalStatus.CANDIDATE,
        policy_review=replace(
            NAVER_VIETNAM_GREENHOUSE.policy_review,
            scope=PolicyScope.PERMISSION_REQUIRED,
        ),
    )
    with pytest.raises(ValueError, match="approved NAVER Vietnam"):
        GreenhouseJobBoardAdapter(config=candidate)

    adapter = GreenhouseJobBoardAdapter(http_fetch=FakeHttpFetch(()))
    registry = AdapterRegistry((adapter,))
    assert registry.resolve_for(NAVER_VIETNAM_GREENHOUSE) is adapter


def test_parse_failure_is_bounded_and_does_not_expose_raw_content() -> None:
    parsed = GreenhouseJobBoardAdapter(http_fetch=FakeHttpFetch(())).parse(
        _snapshot("jobs_malformed.json", "1001")
    )

    assert isinstance(parsed, ParseFailure)
    assert parsed.error_code == "malformed_json"
    assert parsed.stage == "greenhouse_parse"
    assert "jobs" not in parsed.safe_summary
