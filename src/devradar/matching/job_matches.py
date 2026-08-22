"""Bounded synchronous JobMatch generation from local embeddings and structured facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from devradar.catalog.models import Job, JobLevel, JobStatus
from devradar.ingestion.normalization import normalize_text
from devradar.intelligence.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_PROVIDER,
    validate_embedding_vector,
)
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    ExtractionPayload,
)
from devradar.intelligence.models import ExtractionResult, ExtractionValidationStatus, JobEmbedding
from devradar.intelligence.taxonomy import classify_role
from devradar.matching.models import JobMatch, ResumeProfile
from devradar.matching.scoring import (
    SCORING_VERSION,
    JobSkill,
    MatchFacts,
    MatchScore,
    score_match,
)

MAX_STORED_MATCHES = 100
MAX_PROFILE_EMBEDDING_TEXT_CHARS = 2_000
PROFILE_EMBEDDING_INPUT_VERSION = "resume-match-embedding-input-v1"


class MatchProfileUnavailable(LookupError):
    """The owner-scoped profile is not active at a generation boundary."""

    code = "resume_profile_not_found"


@dataclass(frozen=True, slots=True)
class MatchGenerationReport:
    profile_id: UUID
    scoring_version: str
    considered_jobs: int
    available_jobs: int
    unavailable_jobs: int
    stored_matches: int
    created_matches: int
    reused_matches: int
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class _ProfileFacts:
    id: UUID
    owner_hash: str
    content_hash: str
    parser_version: str
    skills: tuple[str, ...]
    roles: tuple[str, ...]
    locations: tuple[str, ...]
    experience_years: Decimal | None


def _load_profile_facts(
    session: Session,
    *,
    profile_id: UUID,
    owner_hash: str,
    now: datetime,
) -> _ProfileFacts:
    profile = session.scalar(
        select(ResumeProfile).where(
            ResumeProfile.id == profile_id,
            ResumeProfile.owner_hash == owner_hash,
            ResumeProfile.deleted_at.is_(None),
            ResumeProfile.expires_at > now,
        )
    )
    if profile is None:
        raise MatchProfileUnavailable
    return _ProfileFacts(
        id=profile.id,
        owner_hash=profile.owner_hash,
        content_hash=profile.content_hash,
        parser_version=profile.parser_version,
        skills=tuple(profile.skills),
        roles=tuple(profile.roles),
        locations=tuple(profile.locations),
        experience_years=profile.experience_years,
    )


def canonical_profile_embedding_text(profile: _ProfileFacts) -> str:
    """Build a bounded input from structured profile fields only."""

    parts: list[str] = []

    def clean_values(values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: set[str] = set()
        for value in values:
            normalized = normalize_text(value).value
            if normalized:
                cleaned.add(normalized)
        return tuple(sorted(cleaned))

    skills = clean_values(profile.skills)
    roles = clean_values(profile.roles)
    locations = clean_values(profile.locations)
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    if roles:
        parts.append("Roles: " + ", ".join(roles))
    if locations:
        parts.append("Locations: " + ", ".join(locations))
    if profile.experience_years is not None:
        parts.append(f"Experience years: {profile.experience_years}")
    text = "\n".join(parts)
    return text[:MAX_PROFILE_EMBEDDING_TEXT_CHARS]


def _compatible_embedding_clause() -> ColumnElement[bool]:
    return and_(
        JobEmbedding.job_id == Job.id,
        JobEmbedding.input_hash == Job.job_content_hash,
        JobEmbedding.input_schema_version == EMBEDDING_INPUT_SCHEMA_VERSION,
        JobEmbedding.provider == EMBEDDING_PROVIDER,
        JobEmbedding.model == EMBEDDING_MODEL_ID,
        JobEmbedding.model_revision == EMBEDDING_MODEL_REVISION,
        JobEmbedding.dimension == EMBEDDING_DIMENSION,
    )


def _job_levels(job: Job) -> tuple[JobLevel, ...]:
    try:
        return tuple(JobLevel(value) for value in job.levels)
    except ValueError:
        return ()


def _job_role(job: Job) -> str | None:
    outcome = classify_role(job.title, job.description_text or "", levels=_job_levels(job))
    if outcome.classification is None:
        return None
    return outcome.classification.role.value


def _extraction_skills(result: ExtractionResult | None) -> tuple[JobSkill, ...] | None:
    if result is None:
        return None
    try:
        payload = ExtractionPayload.model_validate(result.output_data)
    except ValueError:
        return None
    return tuple(JobSkill(skill.name, skill.requirement_type) for skill in payload.skills)


def _job_match_facts(
    profile: _ProfileFacts,
    job: Job,
    extraction: ExtractionResult | None,
    semantic_similarity: Decimal,
) -> MatchFacts:
    locations = tuple(
        value for value in (job.location_city, job.location_province) if value is not None
    )
    return MatchFacts(
        profile_skills=profile.skills,
        job_skills=_extraction_skills(extraction),
        semantic_similarity=semantic_similarity,
        profile_experience_years=profile.experience_years,
        job_experience_min=job.experience_min,
        profile_locations=profile.locations,
        job_locations=locations,
        profile_roles=profile.roles,
        job_role=_job_role(job),
    )


def _current_extractions(
    session: Session,
    jobs: Sequence[Job],
) -> dict[UUID, ExtractionResult]:
    if not jobs:
        return {}
    identity_clauses = [
        and_(
            ExtractionResult.input_ref == job.id,
            ExtractionResult.input_hash == job.job_content_hash,
        )
        for job in jobs
    ]
    results = session.scalars(
        select(ExtractionResult)
        .where(
            or_(*identity_clauses),
            ExtractionResult.schema_version == EXTRACTION_SCHEMA_VERSION,
            ExtractionResult.canonicalization_version == CANONICALIZATION_VERSION,
            ExtractionResult.validation_status == ExtractionValidationStatus.ACCEPTED.value,
        )
        .order_by(ExtractionResult.created_at.desc(), ExtractionResult.id.desc())
    )
    selected: dict[UUID, ExtractionResult] = {}
    for result in results:
        selected.setdefault(result.input_ref, result)
    return selected


def _match_row(
    *,
    profile: _ProfileFacts,
    job: Job,
    score: MatchScore,
) -> dict[str, object]:
    components = score.components
    return {
        "resume_profile_id": profile.id,
        "job_id": job.id,
        "profile_content_hash": profile.content_hash,
        "profile_parser_version": profile.parser_version,
        "job_content_hash": job.job_content_hash,
        "scoring_version": SCORING_VERSION,
        "profile_embedding_input_version": PROFILE_EMBEDDING_INPUT_VERSION,
        "job_embedding_input_schema_version": EMBEDDING_INPUT_SCHEMA_VERSION,
        "overall_score": score.overall_score,
        "evidence_coverage": score.evidence_coverage,
        "skill_score": components.skill,
        "semantic_score": components.semantic,
        "experience_score": components.experience,
        "location_score": components.location,
        "role_score": components.role,
        "matched_skills": list(score.matched_skills),
        "missing_skills": list(score.missing_skills),
        "explanation": list(score.explanation),
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL_ID,
        "embedding_revision": EMBEDDING_MODEL_REVISION,
        "embedding_dimension": EMBEDDING_DIMENSION,
    }


def _persist_current_matches(
    session: Session,
    *,
    profile: _ProfileFacts,
    vector: tuple[float, ...],
    now: datetime,
) -> MatchGenerationReport:
    with session.begin():
        active_profile = session.scalar(
            select(ResumeProfile).where(
                ResumeProfile.id == profile.id,
                ResumeProfile.owner_hash == profile.owner_hash,
                ResumeProfile.deleted_at.is_(None),
                ResumeProfile.expires_at > now,
            )
        )
        if active_profile is None:
            raise MatchProfileUnavailable

        considered_jobs = (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.ACTIVE)
            )
            or 0
        )
        distance = JobEmbedding.embedding.cosine_distance(list(vector)).label("distance")
        rows = session.execute(
            select(Job, distance)
            .join(JobEmbedding, _compatible_embedding_clause())
            .where(Job.status == JobStatus.ACTIVE)
        ).all()
        jobs = [job for job, _distance in rows]
        extractions = _current_extractions(session, jobs)
        scored: list[tuple[Decimal, UUID, Job, MatchScore]] = []
        for job, distance_value in rows:
            similarity = max(
                Decimal("0"), min(Decimal("1"), Decimal("1") - Decimal(str(distance_value)))
            )
            score = score_match(_job_match_facts(profile, job, extractions.get(job.id), similarity))
            scored.append((score.overall_score, job.id, job, score))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[:MAX_STORED_MATCHES]
        created = 0
        key_columns = [
            JobMatch.resume_profile_id,
            JobMatch.job_id,
            JobMatch.profile_content_hash,
            JobMatch.profile_parser_version,
            JobMatch.job_content_hash,
            JobMatch.scoring_version,
            JobMatch.profile_embedding_input_version,
            JobMatch.job_embedding_input_schema_version,
            JobMatch.embedding_provider,
            JobMatch.embedding_model,
            JobMatch.embedding_revision,
            JobMatch.embedding_dimension,
        ]
        for _score, _job_id, job, score in selected:
            result = session.execute(
                insert(JobMatch)
                .values(_match_row(profile=profile, job=job, score=score))
                .on_conflict_do_nothing(index_elements=key_columns)
                .returning(JobMatch.id)
            )
            created += result.scalar_one_or_none() is not None
        return MatchGenerationReport(
            profile_id=profile.id,
            scoring_version=SCORING_VERSION,
            considered_jobs=int(considered_jobs),
            available_jobs=len(rows),
            unavailable_jobs=int(considered_jobs) - len(rows),
            stored_matches=len(selected),
            created_matches=created,
            reused_matches=len(selected) - created,
            generated_at=now,
        )


def generate_job_matches(
    session: Session,
    *,
    profile_id: UUID,
    owner_hash: str,
    now: datetime,
    embed_profile: Callable[[str], Sequence[float]],
) -> MatchGenerationReport:
    """Generate current top matches with local inference outside DB transactions."""

    session.rollback()
    profile = _load_profile_facts(
        session,
        profile_id=profile_id,
        owner_hash=owner_hash,
        now=now,
    )
    profile_text = canonical_profile_embedding_text(profile)
    session.rollback()
    vector = validate_embedding_vector(embed_profile(profile_text))
    session.rollback()
    return _persist_current_matches(session, profile=profile, vector=vector, now=now)
