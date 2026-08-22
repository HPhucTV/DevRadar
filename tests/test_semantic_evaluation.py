from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from devradar.intelligence.semantic_evaluation import (
    SEMANTIC_DATASET_VERSION,
    SemanticEvaluationDataset,
    SemanticEvaluationError,
    SemanticLanguage,
    SemanticSplit,
    evaluate_semantic_retrieval,
    load_semantic_dataset,
)

DATASET_PATH = Path(__file__).parent / "fixtures" / "ai" / "semantic_retrieval_eval_v1.json"
DEVELOPMENT_SELECTION_PATH = (
    Path(__file__).parent / "fixtures" / "ai" / "semantic_retrieval_dev_v2.json"
)


def test_semantic_dataset_is_versioned_synthetic_and_held_out_complete() -> None:
    dataset = load_semantic_dataset(DATASET_PATH)

    assert dataset.dataset_version == SEMANTIC_DATASET_VERSION
    assert dataset.provenance == "project-authored-synthetic-no-third-party-content"
    assert len(dataset.documents) == 12
    assert len(dataset.development_queries) == 4
    assert len(dataset.held_out_queries) == 24
    assert {query.language for query in dataset.held_out_queries} == set(SemanticLanguage)
    assert sum(query.cross_language for query in dataset.held_out_queries) >= 10
    serialized = DATASET_PATH.read_text(encoding="utf-8").casefold()
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert "@" not in serialized


def test_semantic_model_selection_fixture_is_frozen_and_development_only() -> None:
    raw = DEVELOPMENT_SELECTION_PATH.read_bytes()
    payload = json.loads(raw)

    assert payload["datasetVersion"] == "semantic-retrieval-dev-v2"
    assert payload["provenance"] == "project-authored-synthetic-no-third-party-content"
    assert len(payload["documents"]) == 12
    assert len(payload["queries"]) == 24
    assert {query["split"] for query in payload["queries"]} == {"development"}
    assert sum(query["crossLanguage"] for query in payload["queries"]) == 12
    assert len({query["text"].casefold() for query in payload["queries"]}) == 24
    assert sha256(raw).hexdigest() == (
        "9fa2e922c3e4e1d7657d5455fffdbbbd04f6b9173fe7f4d8b48b83cff0c78f29"
    )
    serialized = raw.decode("utf-8").casefold()
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert "@" not in serialized


def test_semantic_dataset_rejects_unknown_relevance_and_duplicate_query() -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["queries"][0]["relevantDocumentIds"] = ["missing-document"]
    with pytest.raises(ValidationError, match="unknown relevant document"):
        SemanticEvaluationDataset.model_validate(payload)

    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["queries"][3]["id"] = payload["queries"][0]["id"]
    with pytest.raises(ValidationError, match="query ids must be unique"):
        SemanticEvaluationDataset.model_validate(payload)


def test_semantic_dataset_exposes_non_empty_splits() -> None:
    dataset = load_semantic_dataset(DATASET_PATH)

    assert all(query.split is SemanticSplit.DEVELOPMENT for query in dataset.development_queries)
    assert all(query.split is SemanticSplit.HELD_OUT for query in dataset.held_out_queries)


def test_semantic_evaluator_reports_reproducible_metrics_and_latency() -> None:
    dataset = load_semantic_dataset(DATASET_PATH)
    document_index = {document.id: index for index, document in enumerate(dataset.documents)}
    document_text_index = {
        document.text: document_index[document.id] for document in dataset.documents
    }
    query_text_index = {
        query.text: document_index[query.relevant_document_ids[0]]
        for query in dataset.development_queries
    }

    def vector(index: int) -> tuple[float, ...]:
        values = [0.0] * 384
        values[index] = 1.0
        return tuple(values)

    report = evaluate_semantic_retrieval(
        dataset,
        split=SemanticSplit.DEVELOPMENT,
        embed_passage=lambda text: vector(document_text_index[text]),
        embed_query=lambda text: vector(query_text_index[text]),
    )

    assert report.top_one_accuracy == 1.0
    assert report.mean_reciprocal_rank == 1.0
    assert report.recall_at_five == 1.0
    assert report.cross_language_top_one_accuracy == 1.0
    assert report.dimension == 384
    assert report.monetary_cost_usd == 0.0
    assert report.to_dict() == report.to_dict()
    assert report.passage_latency_ms_p50 >= 0
    assert report.query_latency_ms_p95 >= 0


def test_semantic_evaluator_uses_document_id_tie_break() -> None:
    dataset = load_semantic_dataset(DATASET_PATH)
    tied = [0.0] * 384
    tied[0] = 1.0

    report = evaluate_semantic_retrieval(
        dataset,
        split=SemanticSplit.DEVELOPMENT,
        embed_passage=lambda _text: tuple(tied),
        embed_query=lambda _text: tuple(tied),
    )

    expected_first_id = min(document.id for document in dataset.documents)
    expected_hits = sum(
        expected_first_id in query.relevant_document_ids for query in dataset.development_queries
    )
    assert report.top_one_accuracy == round(expected_hits / 4, 4)


def test_semantic_evaluator_rejects_zero_or_invalid_vectors() -> None:
    dataset = load_semantic_dataset(DATASET_PATH)

    with pytest.raises(SemanticEvaluationError, match="semantic_vector_zero"):
        evaluate_semantic_retrieval(
            dataset,
            split=SemanticSplit.DEVELOPMENT,
            embed_passage=lambda _text: (0.0,) * 384,
            embed_query=lambda _text: (0.0,) * 384,
        )

    with pytest.raises(SemanticEvaluationError, match="semantic_vector_invalid"):
        evaluate_semantic_retrieval(
            dataset,
            split=SemanticSplit.DEVELOPMENT,
            embed_passage=lambda _text: (1.0,),
            embed_query=lambda _text: (1.0,),
        )
