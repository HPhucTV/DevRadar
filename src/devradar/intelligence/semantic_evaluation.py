"""Fixed synthetic semantic-retrieval evaluation contract for V3 release gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from math import ceil, sqrt
from pathlib import Path
from time import perf_counter
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from devradar.intelligence.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EmbeddingValidationError,
    LocalEmbeddingModel,
    get_embedding_model_path,
    validate_embedding_vector,
)

SEMANTIC_DATASET_VERSION = "semantic-retrieval-eval-v1"
SEMANTIC_DATASET_SCHEMA_VERSION = "semantic-retrieval-eval-schema-v1"
SEMANTIC_DATASET_PROVENANCE = "project-authored-synthetic-no-third-party-content"


class SemanticSplit(StrEnum):
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class SemanticLanguage(StrEnum):
    VI = "vi"
    EN = "en"
    MIXED = "mixed"


class SemanticEvaluationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class SemanticDocument(SemanticEvaluationModel):
    id: str = Field(pattern=r"^job-[a-z0-9-]{3,80}$")
    language: SemanticLanguage
    role: str = Field(pattern=r"^[a-z][a-z0-9-]{1,49}$")
    text: str = Field(min_length=20, max_length=1_000)


class SemanticQuery(SemanticEvaluationModel):
    id: str = Field(pattern=r"^(dev|held)-(vi|en|mixed)-[a-z0-9-]+-[0-9]{3}$")
    split: SemanticSplit
    language: SemanticLanguage
    cross_language: bool
    text: str = Field(min_length=10, max_length=300)
    relevant_document_ids: tuple[str, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        split_prefix = "dev" if self.split is SemanticSplit.DEVELOPMENT else "held"
        if not self.id.startswith(f"{split_prefix}-{self.language.value}-"):
            raise ValueError("query id must encode split and language")
        if len(set(self.relevant_document_ids)) != len(self.relevant_document_ids):
            raise ValueError("relevant document ids must be unique")
        return self


class SemanticEvaluationDataset(SemanticEvaluationModel):
    dataset_version: str
    schema_version: str
    provenance: str
    documents: tuple[SemanticDocument, ...]
    queries: tuple[SemanticQuery, ...]

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.dataset_version != SEMANTIC_DATASET_VERSION:
            raise ValueError(f"datasetVersion must be {SEMANTIC_DATASET_VERSION}")
        if self.schema_version != SEMANTIC_DATASET_SCHEMA_VERSION:
            raise ValueError(f"schemaVersion must be {SEMANTIC_DATASET_SCHEMA_VERSION}")
        if self.provenance != SEMANTIC_DATASET_PROVENANCE:
            raise ValueError("semantic evaluation data must use approved synthetic provenance")

        document_ids = [document.id for document in self.documents]
        if not document_ids or len(document_ids) != len(set(document_ids)):
            raise ValueError("document ids must be non-empty and unique")
        if len({document.text.casefold() for document in self.documents}) != len(self.documents):
            raise ValueError("document texts must be unique")

        query_ids = [query.id for query in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("query ids must be unique")
        if len({query.text.casefold() for query in self.queries}) != len(self.queries):
            raise ValueError("query texts must be unique")
        if not self.development_queries or not self.held_out_queries:
            raise ValueError("development and held-out splits must be non-empty")

        known_documents = set(document_ids)
        for query in self.queries:
            if not set(query.relevant_document_ids) <= known_documents:
                raise ValueError(f"unknown relevant document in query: {query.id}")
        return self

    @property
    def development_queries(self) -> tuple[SemanticQuery, ...]:
        return tuple(query for query in self.queries if query.split is SemanticSplit.DEVELOPMENT)

    @property
    def held_out_queries(self) -> tuple[SemanticQuery, ...]:
        return tuple(query for query in self.queries if query.split is SemanticSplit.HELD_OUT)


class SemanticEvaluationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SemanticEvaluationReport:
    dataset_version: str
    schema_version: str
    model: str
    model_revision: str
    input_schema_version: str
    split: str
    documents: int
    cases: int
    language_cases: dict[str, int]
    cross_language_cases: int
    top_one_accuracy: float
    mean_reciprocal_rank: float
    recall_at_five: float
    cross_language_top_one_accuracy: float
    dimension: int
    finite: bool
    passage_latency_ms_p50: float
    passage_latency_ms_p95: float
    query_latency_ms_p50: float
    query_latency_ms_p95: float
    monetary_cost_usd: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_semantic_dataset(path: Path) -> SemanticEvaluationDataset:
    return SemanticEvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _validated_nonzero_vector(values: Sequence[float]) -> tuple[float, ...]:
    try:
        vector = validate_embedding_vector(values)
    except (EmbeddingValidationError, TypeError, ValueError):
        raise SemanticEvaluationError("semantic_vector_invalid") from None
    if not any(vector):
        raise SemanticEvaluationError("semantic_vector_zero")
    return vector


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(first * second for first, second in zip(left, right, strict=True))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise SemanticEvaluationError("semantic_vector_zero")
    return numerator / (left_norm * right_norm)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _ratio(numerator: float, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_semantic_retrieval(
    dataset: SemanticEvaluationDataset,
    *,
    split: SemanticSplit,
    embed_passage: Callable[[str], Sequence[float]],
    embed_query: Callable[[str], Sequence[float]],
) -> SemanticEvaluationReport:
    queries = (
        dataset.development_queries
        if split is SemanticSplit.DEVELOPMENT
        else dataset.held_out_queries
    )
    if not queries:
        raise SemanticEvaluationError("semantic_evaluation_split_empty")

    passage_latencies: list[float] = []
    document_vectors: dict[str, tuple[float, ...]] = {}
    for document in dataset.documents:
        started_at = perf_counter()
        raw_vector = embed_passage(document.text)
        passage_latencies.append((perf_counter() - started_at) * 1_000)
        document_vectors[document.id] = _validated_nonzero_vector(raw_vector)

    query_latencies: list[float] = []
    top_one_hits = 0
    reciprocal_rank_total = 0.0
    recall_at_five_hits = 0
    cross_language_hits = 0
    cross_language_cases = 0
    for query in queries:
        started_at = perf_counter()
        raw_vector = embed_query(query.text)
        query_latencies.append((perf_counter() - started_at) * 1_000)
        query_vector = _validated_nonzero_vector(raw_vector)
        ranking = sorted(
            dataset.documents,
            key=lambda document: (
                -_cosine(query_vector, document_vectors[document.id]),
                document.id,
            ),
        )
        relevant_ids = set(query.relevant_document_ids)
        top_one_hit = ranking[0].id in relevant_ids
        top_one_hits += top_one_hit
        first_rank = next(
            index for index, document in enumerate(ranking, start=1) if document.id in relevant_ids
        )
        reciprocal_rank_total += 1 / first_rank
        recall_at_five_hits += any(document.id in relevant_ids for document in ranking[:5])
        if query.cross_language:
            cross_language_cases += 1
            cross_language_hits += top_one_hit

    language_cases = Counter(query.language.value for query in queries)
    return SemanticEvaluationReport(
        dataset_version=dataset.dataset_version,
        schema_version=dataset.schema_version,
        model=EMBEDDING_MODEL_ID,
        model_revision=EMBEDDING_MODEL_REVISION,
        input_schema_version=EMBEDDING_INPUT_SCHEMA_VERSION,
        split=split.value,
        documents=len(dataset.documents),
        cases=len(queries),
        language_cases={
            language.value: language_cases[language.value] for language in SemanticLanguage
        },
        cross_language_cases=cross_language_cases,
        top_one_accuracy=_ratio(top_one_hits, len(queries)),
        mean_reciprocal_rank=_ratio(reciprocal_rank_total, len(queries)),
        recall_at_five=_ratio(recall_at_five_hits, len(queries)),
        cross_language_top_one_accuracy=_ratio(cross_language_hits, cross_language_cases),
        dimension=EMBEDDING_DIMENSION,
        finite=True,
        passage_latency_ms_p50=_percentile(passage_latencies, 0.50),
        passage_latency_ms_p95=_percentile(passage_latencies, 0.95),
        query_latency_ms_p50=_percentile(query_latencies, 0.50),
        query_latency_ms_p95=_percentile(query_latencies, 0.95),
        monetary_cost_usd=0.0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devradar-semantic-evaluation")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--split",
        choices=tuple(split.value for split in SemanticSplit),
        default=SemanticSplit.HELD_OUT.value,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_semantic_dataset(args.dataset)
        model = LocalEmbeddingModel(get_embedding_model_path())
        report = evaluate_semantic_retrieval(
            dataset,
            split=SemanticSplit(args.split),
            embed_passage=model.embed_passage,
            embed_query=model.embed_query,
        )
    except Exception:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "semantic_evaluation_failed",
                        "message": "Semantic evaluation could not complete safely.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
