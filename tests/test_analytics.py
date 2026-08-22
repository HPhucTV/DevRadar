from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from devradar.api.analytics import (
    CohortField,
    SkillFrequencyQuery,
    SkillTrendQuery,
    TrendGranularity,
)


def test_skill_trend_query_has_bounded_explicit_window() -> None:
    query = SkillTrendQuery.model_validate(
        {
            "from": "2026-08-01",
            "to": "2026-08-22",
            "cohort": "firstSeenAt",
            "granularity": "week",
        }
    )

    assert query.from_date == date(2026, 8, 1)
    assert query.to_date == date(2026, 8, 22)
    assert query.cohort is CohortField.FIRST_SEEN_AT
    assert query.granularity is TrendGranularity.WEEK


@pytest.mark.parametrize(
    "payload",
    [
        {"from": "2026-08-22", "to": "2026-08-01"},
        {"from": "2025-01-01", "to": "2026-08-22"},
        {"from": "2026-08-01", "to": "2026-08-22", "topSkills": 21},
    ],
)
def test_skill_trend_query_rejects_invalid_or_unbounded_window(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SkillTrendQuery.model_validate(payload)


def test_skill_frequency_date_filter_requires_both_bounds() -> None:
    with pytest.raises(ValidationError):
        SkillFrequencyQuery.model_validate({"from": "2026-08-01"})
