from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from devradar.custom_sources.models import CustomSourceProfileDraft
from devradar.custom_sources.policy import build_custom_fetch_policy
from devradar.custom_sources.service import _adapter_preview
from devradar.ingestion.adapters.custom import CustomSourceAdapter, CustomSourceAdapterError
from devradar.ingestion.contracts import FetchResult, RawSnapshot, RunContext
from devradar.ingestion.safe_http import FetchError, FetchErrorCode

FIXTURES = Path(__file__).parent / "fixtures" / "custom_sources"


def _draft() -> CustomSourceProfileDraft:
    return CustomSourceProfileDraft.from_input(
        name="Example",
        base_url="https://example.test/jobs",
        permission_acknowledged=True,
    )


def _fetch_result(payload: bytes, *, content_type: str = "application/json") -> FetchResult:
    return FetchResult(
        final_url="https://example.test/jobs",
        fetched_at=datetime(2026, 8, 23, 3, 0, tzinfo=UTC),
        http_status=200,
        content_type=content_type,
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


def _run_context() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        source=type("CustomSourceIdentity", (), {"source_key": "custom-example"})(),
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="custom-test",
    )


def test_custom_adapter_discovers_and_reuses_only_profile_results() -> None:
    payload = (FIXTURES / "jobs_json.html").read_bytes()
    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=lambda url, policy: _fetch_result(payload),
    )
    listings = adapter.discover(_run_context())
    assert len(listings) == 1
    assert listings[0].external_id == "json-7"
    assert listings[0].canonical_url == "https://example.test/jobs/json-7"

    fetched = adapter.fetch(listings[0], build_custom_fetch_policy(_draft()))
    assert fetched.raw_content_hash == sha256(payload).hexdigest()

    with pytest.raises(CustomSourceAdapterError, match="current discovery"):
        adapter.fetch(
            type(listings[0])(
                external_id="other",
                canonical_url="https://example.test/jobs/other",
            ),
            build_custom_fetch_policy(_draft()),
        )


def test_preview_keeps_transport_metadata_when_parser_rejects_payload() -> None:
    payload = b'{"jobs": [{"id": "missing-required-fields"}]}'
    fetch_result = FetchResult(
        final_url="https://example.test/jobs/final?token=removed-later",
        fetched_at=datetime(2026, 8, 23, 3, 0, tzinfo=UTC),
        http_status=200,
        content_type="application/json",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
        redirect_chain=("https://example.test/jobs/final?token=removed-later",),
    )
    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=lambda url, policy: fetch_result,
    )

    preview = _adapter_preview(adapter, _run_context())

    assert preview.failures[0].code == "missing_required_field"
    assert preview.final_url == fetch_result.final_url
    assert preview.redirect_chain == fetch_result.redirect_chain


def test_custom_adapter_parses_snapshot_with_provenance() -> None:
    payload = (FIXTURES / "jobs_json.html").read_bytes()
    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=lambda url, policy: _fetch_result(payload),
    )
    listing = adapter.discover(_run_context())[0]
    snapshot = RawSnapshot(
        snapshot_id=uuid4(),
        source_key="custom-example",
        external_id=listing.external_id,
        source_url=listing.canonical_url,
        fetched_at=datetime(2026, 8, 23, 3, 0, tzinfo=UTC),
        content_type="application/json",
        raw_content=payload.decode(),
        raw_content_hash=sha256(payload).hexdigest(),
    )
    parsed = adapter.parse(snapshot)
    assert parsed.raw.title == "Data Platform Engineer"  # type: ignore[union-attr]
    assert parsed.raw.company_name == "Example Data"  # type: ignore[union-attr]
    assert parsed.parser_version == "custom-hybrid-v1"  # type: ignore[union-attr]
    assert any(item.source_path.startswith("json:") for item in parsed.evidence)  # type: ignore[union-attr]


def test_custom_adapter_blocks_permission_challenge_without_retry() -> None:
    def blocked_fetch(url: str, policy: object) -> object:
        raise FetchError(
            FetchErrorCode.HTTP_ERROR,
            "Source returned a protected response.",
            retryable=False,
            http_status=403,
        )

    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=blocked_fetch,  # type: ignore[arg-type]
    )
    with pytest.raises(CustomSourceAdapterError) as captured:
        adapter.discover(_run_context())
    assert captured.value.code == "permission_required"
    assert captured.value.retryable is False


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (404, "policy_blocked", False),
        (500, "server_error", True),
    ],
)
def test_custom_adapter_preserves_http_policy_and_retry_semantics(
    status: int, code: str, retryable: bool
) -> None:
    def failed_fetch(url: str, policy: object) -> object:
        error_code = FetchErrorCode.SERVER_ERROR if status >= 500 else FetchErrorCode.HTTP_ERROR
        raise FetchError(
            error_code,
            "source response",
            retryable=retryable,
            http_status=status,
        )

    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=failed_fetch,  # type: ignore[arg-type]
    )
    with pytest.raises(CustomSourceAdapterError) as captured:
        adapter.discover(_run_context())
    assert captured.value.code == code
    assert captured.value.retryable is retryable


def test_custom_adapter_rejects_candidate_url_outside_saved_boundary() -> None:
    payload = b'{"jobs":[{"id":"external-1","url":"https://other.test/jobs/1",'
    payload += b'"title":"External","company":"Other"}]}'
    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=lambda url, policy: _fetch_result(payload),
    )
    with pytest.raises(CustomSourceAdapterError, match="saved boundary") as captured:
        adapter.discover(_run_context())
    assert captured.value.code == "policy_blocked"


def test_custom_adapter_normalizes_candidate_url_before_persisting() -> None:
    payload = b'{"jobs":[{"id":"case-1","url":"https://EXAMPLE.test/jobs/case-1",'
    payload += b'"title":"Case","company":"Example"}]}'
    adapter = CustomSourceAdapter(
        source_key="custom-example",
        profile=_draft(),
        http_fetch=lambda url, policy: _fetch_result(payload),
    )
    listing = adapter.discover(_run_context())[0]
    assert listing.canonical_url == "https://example.test/jobs/case-1"
    snapshot = RawSnapshot(
        snapshot_id=uuid4(),
        source_key="custom-example",
        external_id=listing.external_id,
        source_url=listing.canonical_url,
        fetched_at=datetime(2026, 8, 23, 3, 0, tzinfo=UTC),
        content_type="application/json",
        raw_content=payload.decode(),
        raw_content_hash=sha256(payload).hexdigest(),
    )
    parsed = adapter.parse(snapshot)
    assert parsed.raw.canonical_url == listing.canonical_url  # type: ignore[union-attr]
