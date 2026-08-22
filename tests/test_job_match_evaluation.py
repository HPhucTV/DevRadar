from __future__ import annotations

import importlib
import json
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "matching" / "job_match_eval_v1.json"
REQUIRED_RISK_TAGS = {
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


class MissingModule(ModuleType):
    def __getattr__(self, name: str) -> object:
        pytest.fail(f"job match evaluation is not implemented: missing {name}")


@pytest.fixture
def evaluation() -> ModuleType:
    try:
        return importlib.import_module("devradar.matching.evaluation")
    except ModuleNotFoundError:
        return MissingModule("devradar.matching.evaluation")


def test_dataset_identity_split_and_risk_coverage(evaluation: ModuleType) -> None:
    dataset = evaluation.load_match_evaluation_dataset(FIXTURE)

    assert dataset.version == "job-match-eval-v1"
    assert dataset.schema_version == "job-match-eval-schema-v1"
    assert dataset.provenance == "project-authored-synthetic-no-third-party-content"
    assert len([case for case in dataset.cases if case.split.value == "development"]) == 4
    assert len([case for case in dataset.cases if case.split.value == "held_out"]) == 8
    assert REQUIRED_RISK_TAGS <= {tag for case in dataset.cases for tag in case.risk_tags}
    assert len(evaluation.dataset_sha256(FIXTURE)) == 64


def test_dataset_rejects_unsafe_or_ambiguous_cases(
    evaluation: ModuleType,
    tmp_path: Path,
) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["provenance"] = "copied-real-cv"
    invalid_provenance = tmp_path / "invalid-provenance.json"
    invalid_provenance.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError):
        evaluation.load_match_evaluation_dataset(invalid_provenance)

    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["cases"][0]["candidates"][1]["id"] = document["cases"][0]["candidates"][0]["id"]
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError):
        evaluation.load_match_evaluation_dataset(duplicate)

    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["cases"][0]["candidates"][0]["semantic"] = 1.01
    out_of_range = tmp_path / "out-of-range.json"
    out_of_range.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError):
        evaluation.load_match_evaluation_dataset(out_of_range)


def test_development_comparison_selects_balanced_role_aware_weights(
    evaluation: ModuleType,
) -> None:
    dataset = evaluation.load_match_evaluation_dataset(FIXTURE)

    skill_heavy = evaluation.evaluate_weight_set(
        dataset,
        evaluation.SKILL_HEAVY_WEIGHTS,
        split="development",
    )
    semantic_heavy = evaluation.evaluate_weight_set(
        dataset,
        evaluation.SEMANTIC_HEAVY_WEIGHTS,
        split="development",
    )
    recommended = evaluation.evaluate_weight_set(
        dataset,
        evaluation.RECOMMENDED_WEIGHTS,
        split="development",
    )

    assert recommended.mrr > skill_heavy.mrr
    assert recommended.mrr > semantic_heavy.mrr
    assert recommended.ndcg_at_5 >= skill_heavy.ndcg_at_5
    assert recommended.ndcg_at_5 >= semantic_heavy.ndcg_at_5


def test_held_out_release_gates_and_missing_semantics(evaluation: ModuleType) -> None:
    dataset = evaluation.load_match_evaluation_dataset(FIXTURE)

    report = evaluation.evaluate_weight_set(
        dataset,
        evaluation.RECOMMENDED_WEIGHTS,
        split="held_out",
    )

    assert report.case_count == 8
    assert report.top1_accuracy >= Decimal("0.875")
    assert report.mrr >= Decimal("0.90")
    assert report.ndcg_at_5 >= Decimal("0.90")
    assert report.score_range_rate == Decimal("1")
    assert report.stable_tie_rate == Decimal("1")
    assert report.missing_behavior_rate == Decimal("1")
    assert report.evidence_closure_rate == Decimal("1")
    assert report.unsupported_claim_rate == Decimal("0")


def test_weight_contract_is_complete_and_normalized(evaluation: ModuleType) -> None:
    assert evaluation.SCORING_VERSION == "job-match-scoring-v1"
    assert set(evaluation.RECOMMENDED_WEIGHTS) == {
        "skill",
        "semantic",
        "experience",
        "location",
        "role",
    }
    assert sum(evaluation.RECOMMENDED_WEIGHTS.values()) == Decimal("1")
