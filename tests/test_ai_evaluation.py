from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from devradar.intelligence.evaluation import (
    BASELINE_VERSION,
    DATASET_VERSION,
    EvaluationDataset,
    EvaluationLanguage,
    EvaluationSplit,
    load_evaluation_dataset,
    run_deterministic_baseline,
)

DATASET_PATH = Path(__file__).parent / "fixtures" / "ai" / "job_extraction_eval_v1.json"


def test_evaluation_dataset_is_versioned_synthetic_split_and_risk_complete() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)

    assert dataset.dataset_version == DATASET_VERSION
    assert dataset.provenance == "project-authored-synthetic-no-third-party-content"
    assert len(dataset.cases) == 12
    assert sum(case.split is EvaluationSplit.DEVELOPMENT for case in dataset.cases) == 4
    held_out = tuple(case for case in dataset.cases if case.split is EvaluationSplit.HELD_OUT)
    assert len(held_out) == 8
    assert {case.language for case in held_out} == set(EvaluationLanguage)
    assert {tag for case in held_out for tag in case.risk_tags} >= {
        "required_optional",
        "ambiguous_level",
        "salary_location_edge",
        "malformed_noisy",
        "prompt_injection",
        "unsupported_field",
    }
    serialized = DATASET_PATH.read_text(encoding="utf-8").casefold()
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert "@" not in serialized


def test_dataset_rejects_missing_evidence_and_duplicate_case_identity() -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["expected"]["skills"][0]["evidence"] = "not in input"
    with pytest.raises(ValidationError, match="skill evidence is not present"):
        EvaluationDataset.model_validate(payload)

    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][7]["id"] = payload["cases"][5]["id"]
    with pytest.raises(ValidationError, match="case ids must be unique"):
        EvaluationDataset.model_validate(payload)


def test_held_out_deterministic_baseline_is_reproducible() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)

    first = run_deterministic_baseline(dataset)
    second = run_deterministic_baseline(dataset)

    assert first == second
    assert first.to_dict() == {
        "dataset_version": DATASET_VERSION,
        "baseline_version": BASELINE_VERSION,
        "split": "held_out",
        "cases": 8,
        "skill_precision": 0.9545,
        "skill_recall": 0.9545,
        "skill_f1": 0.9545,
        "unsupported_skill_rate": 0.0455,
        "level_exact_accuracy": 1.0,
        "experience_exact_accuracy": 0.875,
        "salary_exact_accuracy": 1.0,
        "location_exact_accuracy": 1.0,
        "deterministic_complete_rate": 0.625,
    }
