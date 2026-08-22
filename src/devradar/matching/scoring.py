"""Versioned deterministic primitives shared by match evaluation and runtime scoring."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final

SCORING_VERSION: Final = "job-match-scoring-v1"
COMPONENT_NAMES: Final = ("skill", "semantic", "experience", "location", "role")
SCORE_QUANTUM: Final = Decimal("0.0001")
RECOMMENDED_WEIGHTS: Final[Mapping[str, Decimal]] = MappingProxyType(
    {
        "skill": Decimal("0.40"),
        "semantic": Decimal("0.25"),
        "experience": Decimal("0.15"),
        "location": Decimal("0.10"),
        "role": Decimal("0.10"),
    }
)


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def weighted_component_score(
    components: Mapping[str, Decimal | None],
    weights: Mapping[str, Decimal] = RECOMMENDED_WEIGHTS,
) -> tuple[Decimal, Decimal]:
    """Return conservative overall score and available evidence coverage."""

    if set(components) != set(COMPONENT_NAMES) or set(weights) != set(COMPONENT_NAMES):
        raise ValueError("job_match_component_contract_invalid")
    if sum(weights.values()) != Decimal("1") or any(weight < 0 for weight in weights.values()):
        raise ValueError("job_match_weight_contract_invalid")
    overall = Decimal("0")
    coverage = Decimal("0")
    for name in COMPONENT_NAMES:
        value = components[name]
        if value is None:
            continue
        if value < 0 or value > 1 or not value.is_finite():
            raise ValueError("job_match_component_value_invalid")
        overall += value * weights[name]
        coverage += weights[name]
    return quantize_score(overall), quantize_score(coverage)
