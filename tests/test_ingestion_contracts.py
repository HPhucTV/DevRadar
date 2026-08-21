from datetime import UTC, datetime
from hashlib import sha256

import pytest

from devradar.ingestion.contracts import FetchResult, ParseFailure


def test_fetch_result_requires_payload_hash_match() -> None:
    payload = b"bounded fixture"
    result = FetchResult(
        final_url="https://example.test/jobs/1",
        fetched_at=datetime.now(UTC),
        http_status=200,
        content_type="text/html",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )
    assert result.payload == payload

    with pytest.raises(ValueError, match="does not match"):
        FetchResult(
            final_url=result.final_url,
            fetched_at=result.fetched_at,
            http_status=result.http_status,
            content_type=result.content_type,
            payload=result.payload,
            raw_content_hash="0" * 64,
        )


def test_parse_failure_summary_is_bounded_single_line() -> None:
    with pytest.raises(ValueError, match="bounded single line"):
        ParseFailure(
            error_code="parse_contract_failed",
            stage="parse",
            safe_summary="unsafe\nraw payload",
        )
