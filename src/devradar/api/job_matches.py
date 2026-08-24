"""Owner-scoped JobMatch generation and side-effect-free read API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from devradar.api.common import (
    ERROR_RESPONSES,
    ApiModel,
    DataResponse,
    ErrorResponse,
    ListResponse,
    PaginationQuery,
    pagination_data,
)
from devradar.api.errors import ApiContractError
from devradar.api.resume_profiles import (
    OWNER_HEADER_OPENAPI_EXTRA,
    OwnerHash,
    require_cv_local_enabled,
)
from devradar.catalog.models import Job, JobStatus
from devradar.ingestion.models import Source
from devradar.intelligence.embeddings import (
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_PROVIDER,
    EmbeddingModelUnavailable,
    EmbeddingValidationError,
    get_local_embedding_model,
)
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION as EXTRACTION_CANONICALIZATION_VERSION,
)
from devradar.intelligence.extraction import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)
from devradar.matching.job_matches import (
    PROFILE_EMBEDDING_INPUT_VERSION,
    MatchGenerationReport,
    MatchProfileUnavailable,
    generate_job_matches,
)
from devradar.matching.models import JobMatch
from devradar.matching.resume_profiles import get_active_profile
from devradar.matching.scoring import SCORING_VERSION
from devradar.platform.database import get_database_session
from devradar.source_recipes.visibility import visible_source_condition

router = APIRouter(prefix="/resume-profiles", tags=["job-matches"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class MatchComponentsData(ApiModel):
    skill: Decimal | None
    semantic: Decimal | None
    experience: Decimal | None
    location: Decimal | None
    role: Decimal | None


class MatchJobData(ApiModel):
    title: str
    company_name: str
    location: str | None
    levels: list[str]
    status: JobStatus
    source_url: str


class JobMatchData(ApiModel):
    id: UUID
    job_id: UUID
    overall_score: Decimal
    evidence_coverage: Decimal
    components: MatchComponentsData
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: list[str]
    scoring_version: str
    embedding_model: str
    embedding_revision: str
    created_at: datetime
    job: MatchJobData


class GenerateMatchesData(ApiModel):
    profile_id: UUID
    scoring_version: str
    considered_jobs: int
    available_jobs: int
    unavailable_jobs: int
    stored_matches: int
    created_matches: int
    reused_matches: int
    generated_at: datetime


GenerateMatchesResponse = DataResponse[GenerateMatchesData]
JobMatchListResponse = ListResponse[JobMatchData]


def _validate_match_query(request: Request) -> None:
    allowed = {"page", "pageSize", "minScore"}
    unknown = sorted(set(request.query_params) - allowed)
    if unknown:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "match_query_invalid",
            "Match query contains an unsupported parameter.",
        )


def _match_item(match: JobMatch, job: Job) -> JobMatchData:
    return JobMatchData(
        id=match.id,
        job_id=match.job_id,
        overall_score=match.overall_score,
        evidence_coverage=match.evidence_coverage,
        components=MatchComponentsData(
            skill=match.skill_score,
            semantic=match.semantic_score,
            experience=match.experience_score,
            location=match.location_score,
            role=match.role_score,
        ),
        matched_skills=match.matched_skills,
        missing_skills=match.missing_skills,
        explanation=match.explanation,
        scoring_version=match.scoring_version,
        embedding_model=match.embedding_model,
        embedding_revision=match.embedding_revision,
        created_at=match.created_at,
        job=MatchJobData(
            title=job.title,
            company_name=job.company_name,
            location=job.location_raw,
            levels=job.levels,
            status=job.status,
            source_url=job.canonical_url,
        ),
    )


def _generation_data(report: MatchGenerationReport) -> GenerateMatchesData:
    return GenerateMatchesData(
        profile_id=report.profile_id,
        scoring_version=report.scoring_version,
        considered_jobs=report.considered_jobs,
        available_jobs=report.available_jobs,
        unavailable_jobs=report.unavailable_jobs,
        stored_matches=report.stored_matches,
        created_matches=report.created_matches,
        reused_matches=report.reused_matches,
        generated_at=report.generated_at,
    )


@router.post(
    "/{profileId}/matches",
    response_model=GenerateMatchesResponse,
    dependencies=[Depends(require_cv_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
        404: {"model": ErrorResponse, "description": "Resume profile was not found."},
        503: {"model": ErrorResponse, "description": "Local embedding model is unavailable."},
    },
)
def generate_matches_for_profile(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
) -> GenerateMatchesResponse:
    try:
        if (
            get_active_profile(
                session,
                profile_id=profile_id,
                owner_hash=owner_hash,
                now=datetime.now(UTC),
            )
            is None
        ):
            raise MatchProfileUnavailable
        model = get_local_embedding_model()
        report = generate_job_matches(
            session,
            profile_id=profile_id,
            owner_hash=owner_hash,
            now=datetime.now(UTC),
            embed_profile=model.embed_passage,
        )
    except MatchProfileUnavailable:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    except (EmbeddingModelUnavailable, EmbeddingValidationError):
        raise ApiContractError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "embedding_model_unavailable",
            "Local embedding model is temporarily unavailable.",
        ) from None
    return GenerateMatchesResponse(data=_generation_data(report))


@router.get(
    "/{profileId}/matches",
    response_model=JobMatchListResponse,
    dependencies=[Depends(require_cv_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
        404: {"model": ErrorResponse, "description": "Resume profile was not found."},
    },
)
def list_matches_for_profile(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    min_score: Annotated[Decimal | None, Query(alias="minScore", ge=0, le=1)] = None,
) -> JobMatchListResponse:
    now = datetime.now(UTC)
    profile = get_active_profile(
        session,
        profile_id=profile_id,
        owner_hash=owner_hash,
        now=now,
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    _validate_match_query(request)
    pagination = PaginationQuery(page=page, page_size=page_size)
    current = and_(
        JobMatch.resume_profile_id == profile.id,
        JobMatch.profile_content_hash == profile.content_hash,
        JobMatch.profile_parser_version == profile.parser_version,
        JobMatch.job_content_hash == Job.job_content_hash,
        JobMatch.scoring_version == SCORING_VERSION,
        JobMatch.profile_embedding_input_version == PROFILE_EMBEDDING_INPUT_VERSION,
        JobMatch.job_embedding_input_schema_version == EMBEDDING_INPUT_SCHEMA_VERSION,
        JobMatch.extraction_version == DETERMINISTIC_EXTRACTOR_VERSION,
        JobMatch.extraction_schema_version == EXTRACTION_SCHEMA_VERSION,
        JobMatch.extraction_canonicalization_version == EXTRACTION_CANONICALIZATION_VERSION,
        JobMatch.embedding_provider == EMBEDDING_PROVIDER,
        JobMatch.embedding_model == EMBEDDING_MODEL_ID,
        JobMatch.embedding_revision == EMBEDDING_MODEL_REVISION,
        JobMatch.embedding_dimension == 384,
        Job.status == JobStatus.ACTIVE,
        visible_source_condition(),
    )
    conditions = [current]
    if min_score is not None:
        conditions.append(JobMatch.overall_score >= min_score)
    total_items = (
        session.scalar(
            select(func.count())
            .select_from(JobMatch)
            .join(Job, Job.id == JobMatch.job_id)
            .join(Source, Source.id == Job.source_id)
            .where(*conditions)
        )
        or 0
    )
    rows = session.execute(
        select(JobMatch, Job)
        .join(Job, Job.id == JobMatch.job_id)
        .join(Source, Source.id == Job.source_id)
        .where(*conditions)
        .order_by(JobMatch.overall_score.desc(), JobMatch.job_id.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    ).all()
    return JobMatchListResponse(
        data=[_match_item(match, job) for match, job in rows],
        pagination=pagination_data(pagination, int(total_items)),
    )
