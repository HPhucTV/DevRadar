from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from devradar.custom_sources.models import CustomSourceProfileDraft
from devradar.custom_sources.policy import build_custom_fetch_policy
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
