from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from devradar.ingestion.adapters.vng import (
    VngAdapterError,
    VngCareersAdapter,
    parse_vng_listing_page,
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
    VNG_CAREERS,
    AdapterRegistry,
    PolicyScope,
    SourceConfig,
)

FIXTURES = Path(__file__).parent / "fixtures" / "vng"
TEST_VNG_CONFIG = replace(
    VNG_CAREERS,
    config_version="fixture-v1",
    adapter_settings={
        "job_families": ("Software",),
        "job_group_ids": ("385",),
    },
)
TEST_MULTI_GROUP_CONFIG = replace(
    VNG_CAREERS,
    config_version="fixture-multi-group-v1",
    adapter_settings={
        "job_families": ("Software", "Data Engineering"),
        "job_group_ids": ("385", "457"),
    },
)
PAGE_1_URL = "https://career.vng.com.vn/tim-kiem-viec-lam?job_group=385&page=1"
PAGE_2_URL = "https://career.vng.com.vn/tim-kiem-viec-lam?job_group=385&page=2"
DETAIL_URL = "https://career.vng.com.vn/tim-kiem-viec-lam/chi-tiet/7001-backend-engineer-vi"


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


def _fetch_result(name: str, url: str) -> FetchResult:
    payload = _fixture_bytes(name)
    return FetchResult(
        final_url=url,
        fetched_at=datetime(2026, 8, 21, 5, 6, 7, tzinfo=UTC),
        http_status=200,
        content_type="text/html; charset=utf-8",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


def _run_context(*, source: SourceConfig = TEST_VNG_CONFIG) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        source=source,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="vng-fixture-test",
    )


def _snapshot(name: str, *, external_id: str = "7001", url: str = DETAIL_URL) -> RawSnapshot:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return RawSnapshot(
        snapshot_id=uuid4(),
        source_key=VNG_CAREERS.source_key,
        external_id=external_id,
        source_url=url,
        fetched_at=datetime(2026, 8, 21, 5, 6, 7, tzinfo=UTC),
        content_type="text/html; charset=utf-8",
        raw_content=raw,
        raw_content_hash=sha256(raw.encode("utf-8")).hexdigest(),
    )


def test_discover_validates_all_pages_filters_scope_and_fetches_exact_detail() -> None:
    http_fetch = FakeHttpFetch(
        (
            _fetch_result("list_page_1.html", PAGE_1_URL),
            _fetch_result("list_page_2.html", PAGE_2_URL),
            _fetch_result("detail_happy.html", DETAIL_URL),
        )
    )
    adapter = VngCareersAdapter(config=TEST_VNG_CONFIG, http_fetch=http_fetch)

    listings = adapter.discover(_run_context())

    assert [listing.external_id for listing in listings] == ["7001", "7002", "7003"]
    assert listings[0].metadata["job_family"] == "Tech"
    assert listings[1].metadata["job_family"] is None
    assert all(listing.metadata["approved_job_group"] == "Software" for listing in listings)
    assert http_fetch.calls == [PAGE_1_URL, PAGE_2_URL]

    result = adapter.fetch(listings[0], VNG_CAREERS.fetch_policy)
    assert result.final_url == DETAIL_URL
    assert http_fetch.calls == [PAGE_1_URL, PAGE_2_URL, DETAIL_URL]


def test_discover_queries_each_approved_group_and_deduplicates_same_job() -> None:
    software_url = "https://career.vng.com.vn/tim-kiem-viec-lam?job_group=385&page=1"
    data_url = "https://career.vng.com.vn/tim-kiem-viec-lam?job_group=457&page=1"
    http_fetch = FakeHttpFetch(
        (
            _fetch_result("list_group_software_single.html", software_url),
            _fetch_result("list_group_data_same_job.html", data_url),
        )
    )
    adapter = VngCareersAdapter(
        config=TEST_MULTI_GROUP_CONFIG,
        http_fetch=http_fetch,
    )

    listings = adapter.discover(_run_context(source=TEST_MULTI_GROUP_CONFIG))

    assert [listing.external_id for listing in listings] == ["7001"]
    assert http_fetch.calls == [software_url, data_url]


def test_parse_detail_extracts_plaintext_and_redacts_contact_data() -> None:
    parsed = VngCareersAdapter(
        config=TEST_VNG_CONFIG,
        http_fetch=FakeHttpFetch(()),
    ).parse(_snapshot("detail_happy.html"))

    assert isinstance(parsed, ParsedJob)
    assert parsed.raw.external_id == "7001"
    assert parsed.raw.canonical_url == DETAIL_URL
    assert parsed.raw.title == "Backend Engineer"
    assert parsed.raw.company_name == "VNG"
    assert parsed.raw.location == "Thành phố Hồ Chí Minh"
    assert parsed.raw.salary is None
    assert parsed.raw.level is None
    assert parsed.raw.experience is None
    assert parsed.raw.posted_at is None
    assert parsed.raw.source_fields["post_on_careers_page"] == 1
    assert parsed.raw.description == (
        "Build & own services.\nContact [redacted-email] or [redacted-phone].\nPython\nPostgreSQL"
    )
    assert parsed.normalized_candidates.description_text == parsed.raw.description
    assert "unsafe" not in parsed.raw.description
    assert parsed.normalized_candidates.location_city == "Ho Chi Minh City"
    assert parsed.normalized_candidates.posted_at is None
    assert "contact_data_redacted" in parsed.warnings
    assert "posted_date_not_normalized_without_timezone" not in parsed.warnings
    assert parsed.parser_version == "vng-careers-v2"


def test_empty_listing_is_valid_but_returns_no_in_scope_jobs() -> None:
    page = parse_vng_listing_page(
        _fixture_bytes("list_empty.html"),
        expected_page=1,
        expected_job_group_id="385",
        config=TEST_VNG_CONFIG,
    )

    assert page.total == 0
    assert page.pages == 1
    assert page.all_external_ids == ()
    assert page.listings == ()


@pytest.mark.parametrize(
    ("fixture", "expected_code"),
    [
        ("missing_next_data.html", "layout_regression"),
        ("malformed_next_data.html", "malformed_json"),
    ],
)
def test_listing_fixture_rejects_missing_or_malformed_next_data(
    fixture: str,
    expected_code: str,
) -> None:
    with pytest.raises(VngAdapterError) as captured:
        parse_vng_listing_page(
            _fixture_bytes(fixture),
            expected_page=1,
            expected_job_group_id="385",
            config=TEST_VNG_CONFIG,
        )

    assert captured.value.code == expected_code
    assert '{"props"' not in captured.value.safe_summary


@pytest.mark.parametrize(
    ("second_fixture", "expected_code"),
    [
        ("list_page_2_duplicate.html", "duplicate_job_id"),
        ("list_page_2_pagination_conflict.html", "pagination_conflict"),
    ],
)
def test_discover_rejects_duplicate_or_changed_pagination(
    second_fixture: str,
    expected_code: str,
) -> None:
    adapter = VngCareersAdapter(
        config=TEST_VNG_CONFIG,
        http_fetch=FakeHttpFetch(
            (
                _fetch_result("list_page_1.html", PAGE_1_URL),
                _fetch_result(second_fixture, PAGE_2_URL),
            )
        ),
    )

    with pytest.raises(VngAdapterError) as captured:
        adapter.discover(_run_context())

    assert captured.value.code == expected_code


def test_page_timeout_invalidates_previous_complete_discovery() -> None:
    timeout = FetchError(
        FetchErrorCode.NETWORK_TIMEOUT,
        "Approved source request timed out.",
        retryable=True,
    )
    http_fetch = FakeHttpFetch(
        (
            _fetch_result("list_page_1.html", PAGE_1_URL),
            _fetch_result("list_page_2.html", PAGE_2_URL),
            _fetch_result("list_page_1.html", PAGE_1_URL),
            timeout,
        )
    )
    adapter = VngCareersAdapter(config=TEST_VNG_CONFIG, http_fetch=http_fetch)
    old_listing = adapter.discover(_run_context())[0]

    with pytest.raises(FetchError) as captured:
        adapter.discover(_run_context())
    assert captured.value.code is FetchErrorCode.NETWORK_TIMEOUT

    with pytest.raises(VngAdapterError) as stale:
        adapter.fetch(old_listing, VNG_CAREERS.fetch_policy)
    assert stale.value.code == "listing_not_discovered"


def test_slug_change_keeps_identity_and_changes_canonical_observation() -> None:
    original = parse_vng_listing_page(
        _fixture_bytes("list_page_1.html"),
        expected_page=1,
        expected_job_group_id="385",
        config=TEST_VNG_CONFIG,
    ).listings[0]
    changed = parse_vng_listing_page(
        _fixture_bytes("list_slug_changed.html"),
        expected_page=1,
        expected_job_group_id="385",
        config=TEST_VNG_CONFIG,
    ).listings[0]

    assert original.external_id == changed.external_id == "7001"
    assert original.canonical_url != changed.canonical_url


def test_closed_or_wrong_identity_detail_returns_safe_parse_failure() -> None:
    adapter = VngCareersAdapter(
        config=TEST_VNG_CONFIG,
        http_fetch=FakeHttpFetch(()),
    )
    closed = adapter.parse(_snapshot("detail_closed.html"))
    wrong_id = adapter.parse(_snapshot("detail_happy.html", external_id="9999"))

    assert isinstance(closed, ParseFailure)
    assert closed.error_code == "job_closed"
    assert isinstance(wrong_id, ParseFailure)
    assert wrong_id.error_code == "listing_not_found"
    assert "Backend" not in wrong_id.safe_summary


def test_wrong_run_config_and_candidate_are_rejected_before_http() -> None:
    http_fetch = FakeHttpFetch(())
    adapter = VngCareersAdapter(config=TEST_VNG_CONFIG, http_fetch=http_fetch)
    mismatched = replace(TEST_VNG_CONFIG, config_version="unexpected")

    with pytest.raises(VngAdapterError) as captured:
        adapter.discover(_run_context(source=mismatched))
    assert captured.value.code == "source_config_mismatch"
    assert http_fetch.calls == []

    candidate = replace(
        TEST_VNG_CONFIG,
        approval_status=SourceApprovalStatus.CANDIDATE,
        policy_review=replace(
            TEST_VNG_CONFIG.policy_review,
            scope=PolicyScope.PERMISSION_REQUIRED,
        ),
    )
    with pytest.raises(ValueError, match="approved VNG Careers"):
        VngCareersAdapter(config=candidate)


def test_adapter_satisfies_registered_source_contract() -> None:
    adapter = VngCareersAdapter(
        config=TEST_VNG_CONFIG,
        http_fetch=FakeHttpFetch(()),
    )
    registry = AdapterRegistry((adapter,))
    assert registry.resolve_for(TEST_VNG_CONFIG) is adapter

    forged = ListingRef(
        external_id="7001",
        canonical_url=DETAIL_URL,
    )
    with pytest.raises(VngAdapterError) as captured:
        adapter.fetch(forged, VNG_CAREERS.fetch_policy)
    assert captured.value.code == "listing_not_discovered"
