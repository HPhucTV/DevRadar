"""Frozen synthetic evaluation contract for deterministic JobMatch ranking."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from devradar.matching.scoring import (
    COMPONENT_NAMES,
    RECOMMENDED_WEIGHTS,
    SCORING_VERSION,
    weighted_component_score,
)

EVALUATION_VERSION: Final = "job-match-eval-v1"
EVALUATION_SCHEMA_VERSION: Final = "job-match-eval-schema-v1"
EVALUATION_PROVENANCE: Final = "project-authored-synthetic-no-third-party-content"
REPORT_QUANTUM: Final = Decimal("0.0001")
REQUIRED_RISK_TAGS: Final = frozenset(
    {
        "bilingual",
        "deterministic_tie",
        "missing_experience",
        "missing_extraction",
        "missing_location",
        "missing_role",
        "missing_skill",
        "overqualified",
        "semantic_conflict",
        "sparse_evidence",
    }
)
SKILL_HEAVY_WEIGHTS: Final[Mapping[str, Decimal]] = {
    "skill": Decimal("0.50"),
    "semantic": Decimal("0.20"),
    "experience": Decimal("0.15"),
    "location": Decimal("0.05"),
    "role": Decimal("0.10"),
}
SEMANTIC_HEAVY_WEIGHTS: Final[Mapping[str, Decimal]] = {
    "skill": Decimal("0.30"),
    "semantic": Decimal("0.40"),
    "experience": Decimal("0.15"),
    "location": Decimal("0.05"),
    "role": Decimal("0.10"),
}

BoundedScore = Annotated[Decimal, Field(ge=0, le=1)]


class EvaluationSplit(StrEnum):
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class EvaluationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class MatchEvaluationCandidate(EvaluationModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    skill: BoundedScore | None
    semantic: BoundedScore | None
    experience: BoundedScore | None
    location: BoundedScore | None
    role: BoundedScore | None
    matched_skills: tuple[str, ...] = Field(max_length=50)
    missing_skills: tuple[str, ...] = Field(max_length=50)
    relevance: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def validate_evidence(self) -> MatchEvaluationCandidate:
        matched = tuple(self.matched_skills)
        missing = tuple(self.missing_skills)
        if matched != tuple(sorted(set(matched))) or missing != tuple(sorted(set(missing))):
            raise ValueError("match evaluation skills must be unique and sorted")
        if set(matched) & set(missing):
            raise ValueError("matched and missing skill evidence must be disjoint")
        if self.skill is None and (matched or missing):
            raise ValueError("missing skill component cannot have skill evidence")
        if self.skill is not None and not (matched or missing):
            raise ValueError("available skill component requires skill evidence")
        if all(getattr(self, name) is None for name in COMPONENT_NAMES):
            raise ValueError("candidate requires at least one component")
        return self


class MatchEvaluationCase(EvaluationModel):
    id: str = Field(pattern=r"^(dev|held)-[a-z0-9-]+-[0-9]{3}$")
    split: EvaluationSplit
    risk_tags: tuple[str, ...] = Field(min_length=1, max_length=10)
    candidates: tuple[MatchEvaluationCandidate, ...] = Field(min_length=3, max_length=10)

    @model_validator(mode="after")
    def validate_case(self) -> MatchEvaluationCase:
        if tuple(self.risk_tags) != tuple(sorted(set(self.risk_tags))):
            raise ValueError("risk tags must be unique and sorted")
        candidate_ids = [candidate.id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique within a case")
        if max(candidate.relevance for candidate in self.candidates) == 0:
            raise ValueError("case requires at least one relevant candidate")
        return self


class MatchEvaluationDataset(EvaluationModel):
    version: str
    schema_version: str
    provenance: str
    cases: tuple[MatchEvaluationCase, ...] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def validate_dataset(self) -> MatchEvaluationDataset:
        if self.version != EVALUATION_VERSION:
            raise ValueError("match evaluation version is not supported")
        if self.schema_version != EVALUATION_SCHEMA_VERSION:
            raise ValueError("match evaluation schema is not supported")
        if self.provenance != EVALUATION_PROVENANCE:
            raise ValueError("match evaluation provenance must be project-authored synthetic")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("match evaluation case IDs must be unique")
        split_counts = {
            split: sum(case.split is split for case in self.cases) for split in EvaluationSplit
        }
        if split_counts != {EvaluationSplit.DEVELOPMENT: 4, EvaluationSplit.HELD_OUT: 8}:
            raise ValueError("match evaluation split must be 4 development and 8 held-out")
        tags = {tag for case in self.cases for tag in case.risk_tags}
        if not REQUIRED_RISK_TAGS <= tags:
            raise ValueError("match evaluation risk coverage is incomplete")
        return self


class MatchEvaluationReport(EvaluationModel):
    evaluation_version: str = EVALUATION_VERSION
    evaluation_schema_version: str = EVALUATION_SCHEMA_VERSION
    scoring_version: str = SCORING_VERSION
    split: EvaluationSplit
    case_count: int
    top1_accuracy: Decimal
    mrr: Decimal
    ndcg_at_5: Decimal
    score_range_rate: Decimal
    monotonicity_rate: Decimal
    stable_tie_rate: Decimal
    missing_behavior_rate: Decimal
    evidence_closure_rate: Decimal
    unsupported_claim_rate: Decimal


def _ratio(numerator: Decimal | int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        REPORT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def load_match_evaluation_dataset(path: Path) -> MatchEvaluationDataset:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return MatchEvaluationDataset.model_validate(document)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise ValueError("job_match_evaluation_dataset_invalid") from None


def dataset_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _candidate_components(candidate: MatchEvaluationCandidate) -> dict[str, Decimal | None]:
    return {name: getattr(candidate, name) for name in COMPONENT_NAMES}


def _dcg(relevances: list[int]) -> float:
    total = 0.0
    for index, value in enumerate(relevances):
        total += float(2**value - 1) / math.log2(index + 2)
    return total


def evaluate_weight_set(
    dataset: MatchEvaluationDataset,
    weights: Mapping[str, Decimal],
    *,
    split: str | EvaluationSplit,
) -> MatchEvaluationReport:
    parsed_split = EvaluationSplit(split)
    cases = [case for case in dataset.cases if case.split is parsed_split]
    top1 = 0
    reciprocal_rank = Decimal("0")
    ndcg_total = Decimal("0")
    score_range = 0
    monotonicity = 0
    stable_ties = 0
    missing_behavior = 0
    evidence_closed = 0
    candidate_count = 0
    unsupported_claims = 0
    for case in cases:
        scored: list[tuple[Decimal, Decimal, MatchEvaluationCandidate]] = []
        case_missing_behavior = True
        for candidate in case.candidates:
            components = _candidate_components(candidate)
            score, coverage = weighted_component_score(components, weights)
            expected_score = sum(
                ((components[name] or Decimal("0")) * weights[name] for name in COMPONENT_NAMES),
                Decimal("0"),
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            expected_coverage = sum(
                (weights[name] for name in COMPONENT_NAMES if components[name] is not None),
                Decimal("0"),
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            case_missing_behavior &= score == expected_score and coverage == expected_coverage
            score_range += 0 <= score <= 1 and 0 <= coverage <= 1
            monotonic = True
            for name in COMPONENT_NAMES:
                value = components[name]
                if value is None or value == 1:
                    continue
                increased = dict(components)
                increased[name] = min(Decimal("1"), value + Decimal("0.0001"))
                increased_score, _ = weighted_component_score(increased, weights)
                monotonic &= increased_score >= score
            monotonicity += monotonic
            matched = candidate.matched_skills
            missing = candidate.missing_skills
            closed = (
                matched == tuple(sorted(set(matched)))
                and missing == tuple(sorted(set(missing)))
                and not (set(matched) & set(missing))
            )
            evidence_closed += closed
            unsupported_claims += not closed
            candidate_count += 1
            scored.append((score, coverage, candidate))
        ordered = sorted(scored, key=lambda item: (-item[0], item[2].id))
        score_groups: dict[Decimal, list[str]] = {}
        for score, _coverage, candidate in scored:
            score_groups.setdefault(score, []).append(candidate.id)
        expected_order = [
            candidate_id
            for score in sorted(score_groups, reverse=True)
            for candidate_id in sorted(score_groups[score])
        ]
        stable_ties += [item[2].id for item in ordered] == expected_order
        missing_behavior += case_missing_behavior
        highest_relevance = max(item[2].relevance for item in ordered)
        top1 += ordered[0][2].relevance == highest_relevance
        first_best_rank = next(
            index
            for index, item in enumerate(ordered, start=1)
            if item[2].relevance == highest_relevance
        )
        reciprocal_rank += Decimal("1") / Decimal(first_best_rank)
        actual_relevance = [item[2].relevance for item in ordered[:5]]
        ideal_relevance = sorted(
            (candidate.relevance for candidate in case.candidates), reverse=True
        )[:5]
        ideal_dcg = _dcg(ideal_relevance)
        ndcg_total += Decimal(str(_dcg(actual_relevance) / ideal_dcg if ideal_dcg else 0))
    case_count = len(cases)
    return MatchEvaluationReport(
        split=parsed_split,
        case_count=case_count,
        top1_accuracy=_ratio(top1, case_count),
        mrr=_ratio(reciprocal_rank, case_count),
        ndcg_at_5=_ratio(ndcg_total, case_count),
        score_range_rate=_ratio(score_range, candidate_count),
        monotonicity_rate=_ratio(monotonicity, candidate_count),
        stable_tie_rate=_ratio(stable_ties, case_count),
        missing_behavior_rate=_ratio(missing_behavior, case_count),
        evidence_closure_rate=_ratio(evidence_closed, candidate_count),
        unsupported_claim_rate=_ratio(unsupported_claims, candidate_count),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="devradar-job-match-evaluation")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=[item.value for item in EvaluationSplit], required=True)
    parser.add_argument(
        "--weights",
        choices=("skill-heavy", "semantic-heavy", "recommended"),
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dataset = load_match_evaluation_dataset(args.dataset)
    weights = {
        "skill-heavy": SKILL_HEAVY_WEIGHTS,
        "semantic-heavy": SEMANTIC_HEAVY_WEIGHTS,
        "recommended": RECOMMENDED_WEIGHTS,
    }[args.weights]
    report = evaluate_weight_set(dataset, weights, split=args.split)
    output = report.model_dump(mode="json", by_alias=True)
    output["datasetSha256"] = dataset_sha256(args.dataset)
    output["weights"] = {name: str(value) for name, value in weights.items()}
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
