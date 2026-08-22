"""Fixed local embedding boundary and version-safe input canonicalization."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.catalog.models import Job
from devradar.intelligence.models import JobEmbedding

EMBEDDING_PROVIDER = "local_fastembed"
EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"
EMBEDDING_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
EMBEDDING_DIMENSION = 384
EMBEDDING_INPUT_SCHEMA_VERSION = "job-embedding-input-v1"
MAX_EMBEDDING_TEXT_CHARS = 12_000
MAX_QUERY_CHARS = 300
EMBEDDING_MODEL_PATH_ENV = "DEVRADAR_EMBEDDING_MODEL_PATH"

_REQUIRED_MODEL_FILES = (
    "config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "onnx/model.onnx",
)
_MODEL_FILE_SHA256 = {
    "config.json": "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959",
    "special_tokens_map.json": "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "tokenizer_config.json": "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
    "onnx/model.onnx": "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665",
}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")

RawEmbedCallable = Callable[[tuple[str, ...]], Iterable[Iterable[float]]]


@dataclass(frozen=True, slots=True)
class EmbeddingKey:
    job_id: UUID
    input_hash: str
    input_schema_version: str
    provider: str
    model: str
    model_revision: str
    dimension: int

    @classmethod
    def for_job(cls, job: Job) -> EmbeddingKey:
        return cls(
            job_id=job.id,
            input_hash=job.job_content_hash,
            input_schema_version=EMBEDDING_INPUT_SCHEMA_VERSION,
            provider=EMBEDDING_PROVIDER,
            model=EMBEDDING_MODEL_ID,
            model_revision=EMBEDDING_MODEL_REVISION,
            dimension=EMBEDDING_DIMENSION,
        )


class EmbeddingValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EmbeddingModelUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("embedding_model_unavailable")
        self.code = "embedding_model_unavailable"


@dataclass(frozen=True, slots=True)
class EmbeddingBackfillReport:
    selected: int
    created: int
    cache_hits: int
    stale_skipped: int


def _clean_text(value: str) -> str:
    return _WHITESPACE.sub(" ", _CONTROL_CHARACTERS.sub(" ", value)).strip()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_files_match(model_path: Path) -> bool:
    return all(
        (model_path / relative_path).is_file()
        and _file_sha256(model_path / relative_path) == expected_hash
        for relative_path, expected_hash in _MODEL_FILE_SHA256.items()
    )


def get_embedding_model_path() -> Path:
    configured = os.environ.get(EMBEDDING_MODEL_PATH_ENV)
    if configured:
        return Path(configured)
    return Path("data/models") / f"multilingual-e5-small-{EMBEDDING_MODEL_REVISION}"


def download_embedding_model(target: Path) -> Path:
    """Download only the fixed model revision to an operator-selected local directory."""

    from huggingface_hub import snapshot_download

    try:
        downloaded = Path(
            snapshot_download(
                repo_id=EMBEDDING_MODEL_ID,
                revision=EMBEDDING_MODEL_REVISION,
                local_dir=target,
                allow_patterns=list(_REQUIRED_MODEL_FILES),
            )
        )
    except Exception:
        raise EmbeddingModelUnavailable from None
    if not _model_files_match(downloaded):
        raise EmbeddingModelUnavailable
    return downloaded.resolve()


def canonical_job_embedding_text(job: Job) -> str:
    """Build bounded, deterministic local input from canonical Job text."""

    title = _clean_text(job.title)
    description = _clean_text(job.description_text or "")
    text = f"Title: {title}"
    if description:
        text += f"\nDescription: {description}"
    return text[:MAX_EMBEDDING_TEXT_CHARS]


def validate_embedding_vector(values: Sequence[float]) -> tuple[float, ...]:
    if len(values) != EMBEDDING_DIMENSION:
        raise EmbeddingValidationError("embedding_vector_invalid")
    parsed: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise EmbeddingValidationError("embedding_vector_invalid")
        number = float(value)
        if not isfinite(number):
            raise EmbeddingValidationError("embedding_vector_invalid")
        parsed.append(number)
    return tuple(parsed)


def load_job_embedding(session: Session, key: EmbeddingKey) -> JobEmbedding | None:
    return session.scalar(
        select(JobEmbedding).where(
            JobEmbedding.job_id == key.job_id,
            JobEmbedding.input_hash == key.input_hash,
            JobEmbedding.input_schema_version == key.input_schema_version,
            JobEmbedding.provider == key.provider,
            JobEmbedding.model == key.model,
            JobEmbedding.model_revision == key.model_revision,
            JobEmbedding.dimension == key.dimension,
        )
    )


def persist_job_embedding(
    session: Session,
    *,
    key: EmbeddingKey,
    vector: Sequence[float],
    latency_ms: int | None,
) -> tuple[JobEmbedding, bool]:
    existing = load_job_embedding(session, key)
    if existing is not None:
        return existing, True
    if latency_ms is not None and latency_ms < 0:
        raise EmbeddingValidationError("embedding_latency_invalid")
    validated = validate_embedding_vector(vector)
    result = JobEmbedding(
        job_id=key.job_id,
        input_hash=key.input_hash,
        input_schema_version=key.input_schema_version,
        provider=key.provider,
        model=key.model,
        model_revision=key.model_revision,
        dimension=key.dimension,
        embedding=list(validated),
        latency_ms=latency_ms,
    )
    try:
        with session.begin_nested():
            session.add(result)
            session.flush()
    except IntegrityError:
        winner = load_job_embedding(session, key)
        if winner is None:
            raise
        return winner, True
    return result, False


def _missing_embedding_clause() -> ColumnElement[bool]:
    return ~exists(
        select(JobEmbedding.id).where(
            JobEmbedding.job_id == Job.id,
            JobEmbedding.input_hash == Job.job_content_hash,
            JobEmbedding.input_schema_version == EMBEDDING_INPUT_SCHEMA_VERSION,
            JobEmbedding.provider == EMBEDDING_PROVIDER,
            JobEmbedding.model == EMBEDDING_MODEL_ID,
            JobEmbedding.model_revision == EMBEDDING_MODEL_REVISION,
            JobEmbedding.dimension == EMBEDDING_DIMENSION,
        )
    )


def backfill_job_embeddings(
    session: Session,
    *,
    embed_passage: Callable[[str], Sequence[float]],
    max_items: int,
) -> EmbeddingBackfillReport:
    if not 1 <= max_items <= 1_000:
        raise EmbeddingValidationError("embedding_batch_size_invalid")

    with session.begin():
        job_ids = tuple(
            session.scalars(
                select(Job.id)
                .where(_missing_embedding_clause())
                .order_by(Job.id.asc())
                .limit(max_items)
            )
        )

    created = 0
    cache_hits = 0
    stale_skipped = 0
    for job_id in job_ids:
        with session.begin():
            job = session.get_one(Job, job_id)
            key = EmbeddingKey.for_job(job)
            text_value = canonical_job_embedding_text(job)

        started_at = perf_counter()
        vector = embed_passage(text_value)
        latency_ms = round((perf_counter() - started_at) * 1_000)

        with session.begin():
            current_job = session.get_one(Job, job_id)
            if current_job.job_content_hash != key.input_hash:
                stale_skipped += 1
                continue
            _, cache_hit = persist_job_embedding(
                session,
                key=key,
                vector=vector,
                latency_ms=latency_ms,
            )
            cache_hits += cache_hit
            created += not cache_hit

    return EmbeddingBackfillReport(
        selected=len(job_ids),
        created=created,
        cache_hits=cache_hits,
        stale_skipped=stale_skipped,
    )


class LocalEmbeddingModel:
    """Local-only fixed-revision E5 inference; never downloads during inference."""

    def __init__(self, model_path: Path, *, embed: RawEmbedCallable | None = None) -> None:
        resolved_path = model_path.resolve()
        if not resolved_path.is_dir() or any(
            not (resolved_path / relative_path).is_file() for relative_path in _REQUIRED_MODEL_FILES
        ):
            raise EmbeddingModelUnavailable
        if embed is None and not _model_files_match(resolved_path):
            raise EmbeddingModelUnavailable
        self._embed = embed or self._load_fastembed(resolved_path)

    @staticmethod
    def _load_fastembed(model_path: Path) -> RawEmbedCallable:
        try:
            from fastembed import TextEmbedding
            from fastembed.common.model_description import ModelSource, PoolingType
        except ImportError:
            raise EmbeddingModelUnavailable from None

        if not any(
            item["model"] == EMBEDDING_MODEL_ID for item in TextEmbedding.list_supported_models()
        ):
            TextEmbedding.add_custom_model(
                model=EMBEDDING_MODEL_ID,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=EMBEDDING_MODEL_ID),
                dim=EMBEDDING_DIMENSION,
                model_file="onnx/model.onnx",
            )
        try:
            model = TextEmbedding(
                model_name=EMBEDDING_MODEL_ID,
                specific_model_path=str(model_path),
                providers=["CPUExecutionProvider"],
                local_files_only=True,
            )
        except Exception:
            raise EmbeddingModelUnavailable from None

        def embed(values: tuple[str, ...]) -> Iterable[Iterable[float]]:
            return model.embed(values)

        return embed

    def _embed_one(self, text: str) -> tuple[float, ...]:
        try:
            vectors = tuple(
                tuple(float(item) for item in vector) for vector in self._embed((text,))
            )
        except Exception:
            raise EmbeddingModelUnavailable from None
        if len(vectors) != 1:
            raise EmbeddingValidationError("embedding_vector_invalid")
        return validate_embedding_vector(vectors[0])

    def embed_query(self, query: str) -> tuple[float, ...]:
        cleaned = _clean_text(query)
        if not cleaned or len(cleaned) > MAX_QUERY_CHARS:
            raise EmbeddingValidationError("embedding_query_invalid")
        return self._embed_one(f"query: {cleaned}")

    def embed_passage(self, text: str) -> tuple[float, ...]:
        cleaned = _clean_text(text)
        if not cleaned or len(cleaned) > MAX_EMBEDDING_TEXT_CHARS:
            raise EmbeddingValidationError("embedding_input_invalid")
        return self._embed_one(f"passage: {cleaned}")


@lru_cache(maxsize=1)
def get_local_embedding_model() -> LocalEmbeddingModel:
    return LocalEmbeddingModel(get_embedding_model_path())
