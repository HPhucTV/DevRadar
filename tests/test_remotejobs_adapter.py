from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from devradar.ingestion.adapters.remotejobs import RemoteJobsApiAdapter
from devradar.ingestion.contracts import (
    FetchResult,
    ParsedJob,
    ParseFailure,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.source_registry import REMOTEJOBS_ORG, FetchPolicy, SourceConfig

FIXTURES = Path(__file__).parent / "fixtures" / "remotejobs"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _result(payload: bytes, *, url: str) -> FetchResult:
    return FetchResult(
        final_url=url,
        fetched_at=datetime.now(UTC),
        http_status=200,
        content_type="application/json",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


def _context(config: SourceConfig = REMOTEJOBS_ORG) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        source=config,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="remotejobs-test",
    )


def test_remotejobs_discovery_is_allowlisted_and_fetch_reuses_page_payload() -> None:
    config = replace(
        REMOTEJOBS_ORG,
        adapter_settings={"categories": ("programming",), "page_size": "50"},
    )
    payload = json.loads(_payload("jobs_happy.json"))
    payload["data"] = [payload["data"][0]]
    payload["pagination"] = {"total": 1, "limit": 50, "offset": 0, "has_more": False}
    page_payload = json.dumps(payload).encode()
    page_url = f"{config.base_url}?category=programming&limit=50&offset=0"
    captured: list[str] = []

    def fake_fetch(url: str, _policy: FetchPolicy) -> FetchResult:
        captured.append(url)
        return _result(page_payload, url=url)

    adapter = RemoteJobsApiAdapter(config=config, http_fetch=fake_fetch)
    listings = adapter.discover(_context(config))

    assert len(listings) == 1
    assert listings[0].external_id == "8320d0d0-6f30-4c38-81d7-149a2ddbe565"
    assert captured == [page_url]
    fetched = adapter.fetch(listings[0], config.fetch_policy)
    assert fetched.payload == page_payload


def test_remotejobs_discovery_skips_same_uuid_duplicate_but_rejects_url_conflict() -> None:
    config = replace(
        REMOTEJOBS_ORG,
        adapter_settings={"categories": ("programming",), "page_size": "50"},
    )
    payload = json.loads(_payload("jobs_happy.json"))
    payload["data"] = [payload["data"][0], payload["data"][0]]
    payload["pagination"] = {"total": 2, "limit": 50, "offset": 0, "has_more": False}
    page_payload = json.dumps(payload).encode()
    adapter = RemoteJobsApiAdapter(
        config=config,
        http_fetch=lambda url, _policy: _result(page_payload, url=url),
    )

    assert len(adapter.discover(_context(config))) == 1

    payload["data"][1] = dict(payload["data"][1])
    payload["data"][1]["id"] = payload["data"][0]["id"]
    payload["data"][1]["url"] = "https://remotejobs.org/remote-jobs/conflicting-url"
    payload["data"][1]["category"] = payload["data"][0]["category"]
    conflict_payload = json.dumps(payload).encode()
    conflict_adapter = RemoteJobsApiAdapter(
        config=config,
        http_fetch=lambda url, _policy: _result(conflict_payload, url=url),
    )

    try:
        conflict_adapter.discover(_context(config))
    except Exception as error:
        assert getattr(error, "code", None) == "duplicate_job_conflict"
    else:
        raise AssertionError("conflicting UUID URL must fail closed")


def test_remotejobs_discovery_accepts_terminal_page_overrun_but_not_underrun() -> None:
    config = replace(
        REMOTEJOBS_ORG,
        adapter_settings={"categories": ("programming",), "page_size": "50"},
    )
    payload = json.loads(_payload("jobs_happy.json"))
    payload["data"][1]["category"] = payload["data"][0]["category"]
    payload["pagination"] = {"total": 1, "limit": 50, "offset": 0, "has_more": False}
    overrun = json.dumps(payload).encode()
    adapter = RemoteJobsApiAdapter(
        config=config,
        http_fetch=lambda url, _policy: _result(overrun, url=url),
    )
    assert len(adapter.discover(_context(config))) == 2

    payload["pagination"]["total"] = 3
    underrun = json.dumps(payload).encode()
    failing_adapter = RemoteJobsApiAdapter(
        config=config,
        http_fetch=lambda url, _policy: _result(underrun, url=url),
    )
    try:
        failing_adapter.discover(_context(config))
    except Exception as error:
        assert getattr(error, "code", None) == "coverage_mismatch"
    else:
        raise AssertionError("terminal page underrun must fail closed")


def test_remotejobs_parser_preserves_raw_salary_and_does_not_follow_apply_url() -> None:
    adapter = RemoteJobsApiAdapter()
    payload = _payload("jobs_happy.json")
    source_url = (
        "https://remotejobs.org/remote-jobs/integration-engineer-internetwork-consulting-services"
    )
    parsed = adapter.parse(
        RawSnapshot(
            snapshot_id=uuid4(),
            source_key=REMOTEJOBS_ORG.source_key,
            external_id="8320d0d0-6f30-4c38-81d7-149a2ddbe565",
            source_url=source_url,
            fetched_at=datetime.now(UTC),
            content_type="application/json",
            raw_content=payload.decode("utf-8"),
            raw_content_hash=sha256(payload).hexdigest(),
        )
    )

    assert isinstance(parsed, ParsedJob)
    assert parsed.raw.salary == "$80,000 - $120,000"
    assert parsed.normalized_candidates.salary_min is None
    assert parsed.normalized_candidates.salary_max is None
    assert parsed.normalized_candidates.currency is None
    assert parsed.raw.posted_at == "2026-08-22T08:00:00Z"
    assert "salary_currency_not_inferred" in parsed.warnings
    apply_url = parsed.raw.source_fields["apply_url"]
    assert isinstance(apply_url, str)
    assert apply_url.startswith("https://")
    assert all("apply" not in evidence.source_path for evidence in parsed.evidence)


def test_remotejobs_parser_rejects_malformed_uuid_without_leaking_content() -> None:
    payload = _payload("jobs_malformed.json")
    parsed = RemoteJobsApiAdapter().parse(
        RawSnapshot(
            snapshot_id=uuid4(),
            source_key=REMOTEJOBS_ORG.source_key,
            external_id=str(UUID("8320d0d0-6f30-4c38-81d7-149a2ddbe565")),
            source_url="https://remotejobs.org/remote-jobs/integration-engineer-internetwork-consulting-services",
            fetched_at=datetime.now(UTC),
            content_type="application/json",
            raw_content=payload.decode("utf-8"),
            raw_content_hash=sha256(payload).hexdigest(),
        )
    )

    assert isinstance(parsed, ParseFailure)
    assert parsed.error_code == "layout_regression"
    assert "not-a-uuid" not in parsed.safe_summary
