from __future__ import annotations

import pytest
from pydantic import ValidationError

from devradar.api.jobs import JobQuery, JobSummary, SearchMode


def test_job_query_defaults_text_query_to_keyword_search() -> None:
    filters = JobQuery.model_validate({"query": "  backend Python  "})

    assert filters.query == "backend Python"
    assert filters.search_mode is SearchMode.KEYWORD


def test_job_query_requires_query_for_explicit_search_mode() -> None:
    with pytest.raises(ValidationError):
        JobQuery.model_validate({"searchMode": "semantic"})


@pytest.mark.parametrize("query", [" ", "x" * 301])
def test_job_query_bounds_untrusted_search_text(query: str) -> None:
    with pytest.raises(ValidationError):
        JobQuery.model_validate({"query": query, "searchMode": "semantic"})


def test_job_summary_exposes_nullable_relevance_without_vector() -> None:
    assert "relevance_score" in JobSummary.model_fields
    assert JobSummary.model_fields["relevance_score"].default is None
