from __future__ import annotations

import os
from datetime import UTC, datetime
from math import inf, nan
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pgvector.sqlalchemy import VECTOR

from devradar.catalog.models import Job, JobStatus
from devradar.intelligence.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    MAX_EMBEDDING_TEXT_CHARS,
    EmbeddingKey,
    EmbeddingModelUnavailable,
    EmbeddingValidationError,
    LocalEmbeddingModel,
    canonical_job_embedding_text,
    get_local_embedding_model,
    validate_embedding_vector,
)
from devradar.intelligence.models import JobEmbedding


def _job(*, title: str = "Backend Engineer", description: str | None = None) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=uuid4(),
        source_id=uuid4(),
        canonical_url="https://careers.example.test/jobs/1",
        title=title,
        company_name="Example",
        description_text=description,
        levels=["senior"],
        first_seen_at=now,
        last_seen_at=now,
        status=JobStatus.ACTIVE,
        current_snapshot_id=uuid4(),
        job_content_hash="a" * 64,
    )


def test_canonical_embedding_text_is_bounded_and_stable() -> None:
    job = _job(
        title="  Backend\r\nEngineer  ",
        description="Build\x00 APIs\r\nwith Python. " + ("x" * 20_000),
    )

    first = canonical_job_embedding_text(job)
    second = canonical_job_embedding_text(job)

    assert first == second
    assert first.startswith("Title: Backend Engineer\nDescription: Build APIs with Python.")
    assert len(first) == MAX_EMBEDDING_TEXT_CHARS
    assert "\x00" not in first
    assert EMBEDDING_INPUT_SCHEMA_VERSION == "job-embedding-input-v2"


def test_embedding_vector_requires_exact_finite_dimension() -> None:
    valid = validate_embedding_vector([0.0] * EMBEDDING_DIMENSION)

    assert len(valid) == EMBEDDING_DIMENSION
    assert EMBEDDING_DIMENSION == 384
    for invalid in (
        [0.0] * (EMBEDDING_DIMENSION - 1),
        [0.0] * (EMBEDDING_DIMENSION - 1) + [nan],
        [0.0] * (EMBEDDING_DIMENSION - 1) + [inf],
    ):
        with pytest.raises(EmbeddingValidationError, match="embedding_vector_invalid"):
            validate_embedding_vector(invalid)


def test_local_model_requires_preloaded_fixed_revision_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing-model"

    with pytest.raises(EmbeddingModelUnavailable, match="embedding_model_unavailable"):
        LocalEmbeddingModel(missing)

    assert EMBEDDING_MODEL_ID == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert EMBEDDING_MODEL_REVISION == "faf4aa4225822f3bc6376869cb1164e8e3feedd0"


def test_local_model_enables_telemetry_disable_before_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    fake_model = object()
    monkeypatch.setattr(
        "devradar.intelligence.embeddings.LocalEmbeddingModel",
        lambda _path: fake_model,
    )
    get_local_embedding_model.cache_clear()
    try:
        assert get_local_embedding_model() is fake_model
        assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
    finally:
        get_local_embedding_model.cache_clear()


def test_local_model_overrides_inherited_telemetry_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    monkeypatch.setattr(
        "devradar.intelligence.embeddings.LocalEmbeddingModel",
        lambda _path: object(),
    )
    get_local_embedding_model.cache_clear()
    try:
        get_local_embedding_model()
        assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
    finally:
        get_local_embedding_model.cache_clear()


def test_local_model_normalizes_query_and_passage_without_logging_content(tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    for relative_path in (
        "config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model_optimized.onnx",
    ):
        path = model_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    captured: list[str] = []

    def fake_embed(values: tuple[str, ...]) -> list[list[float]]:
        captured.extend(values)
        return [[0.0] * EMBEDDING_DIMENSION for _ in values]

    model = LocalEmbeddingModel(model_path, embed=fake_embed)

    query = model.embed_query("  backend\nPython  ")
    passage = model.embed_passage("Backend role")

    assert len(query) == EMBEDDING_DIMENSION
    assert len(passage) == EMBEDDING_DIMENSION
    assert captured == ["backend Python", "Backend role"]


def test_embedding_key_and_mapping_pin_every_compatibility_field() -> None:
    job = _job(description="Python backend")

    key = EmbeddingKey.for_job(job)

    assert key.job_id == job.id
    assert key.input_hash == job.job_content_hash
    assert key.input_schema_version == EMBEDDING_INPUT_SCHEMA_VERSION
    assert key.model == EMBEDDING_MODEL_ID
    assert key.model_revision == EMBEDDING_MODEL_REVISION
    assert key.dimension == EMBEDDING_DIMENSION
    embedding_type = cast(VECTOR, JobEmbedding.__table__.c.embedding.type)
    assert embedding_type.dim == EMBEDDING_DIMENSION
