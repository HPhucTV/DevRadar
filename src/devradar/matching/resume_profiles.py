"""Owner-scoped ResumeProfile persistence and lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from devradar.matching.models import ResumeProfile
from devradar.matching.resume_profile_parser import ResumeProfileDraft

PROFILE_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class ProfileWriteOutcome:
    profile: ResumeProfile
    reused: bool


def _logical_profile_query(
    owner_hash: str,
    draft: ResumeProfileDraft,
) -> Select[tuple[ResumeProfile]]:
    return select(ResumeProfile).where(
        ResumeProfile.owner_hash == owner_hash,
        ResumeProfile.content_hash == draft.content_hash,
        ResumeProfile.parser_version == draft.parser_version,
        ResumeProfile.deleted_at.is_(None),
    )


def create_or_reuse_profile(
    session: Session,
    *,
    owner_hash: str,
    draft: ResumeProfileDraft,
    now: datetime,
) -> ProfileWriteOutcome:
    """Reuse a live logical profile or atomically insert its next short-lived version."""

    existing = session.scalar(_logical_profile_query(owner_hash, draft).with_for_update())
    if existing is not None and existing.expires_at > now:
        return ProfileWriteOutcome(profile=existing, reused=True)
    if existing is not None:
        existing.deleted_at = now
        session.flush()

    profile_id = session.scalar(
        insert(ResumeProfile)
        .values(
            owner_hash=owner_hash,
            content_hash=draft.content_hash,
            file_name_sanitized=draft.file_name_sanitized,
            source_format=draft.source_format,
            parser_version=draft.parser_version,
            extraction_status=draft.extraction_status,
            skills=list(draft.skills),
            roles=list(draft.roles),
            locations=list(draft.locations),
            experience_years=draft.experience_years,
            retention_mode="ephemeral",
            created_at=now,
            expires_at=now + PROFILE_TTL,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ResumeProfile.owner_hash,
                ResumeProfile.content_hash,
                ResumeProfile.parser_version,
            ],
            index_where=ResumeProfile.deleted_at.is_(None),
        )
        .returning(ResumeProfile.id)
    )
    if profile_id is not None:
        profile = session.get(ResumeProfile, profile_id)
        if profile is None:
            raise RuntimeError("inserted ResumeProfile could not be re-read")
        return ProfileWriteOutcome(profile=profile, reused=False)

    winner = session.scalar(_logical_profile_query(owner_hash, draft))
    if winner is None:
        raise RuntimeError("ResumeProfile replay winner could not be re-read")
    return ProfileWriteOutcome(profile=winner, reused=True)


def get_active_profile(
    session: Session,
    *,
    profile_id: UUID,
    owner_hash: str,
    now: datetime,
) -> ResumeProfile | None:
    return session.scalar(
        select(ResumeProfile).where(
            ResumeProfile.id == profile_id,
            ResumeProfile.owner_hash == owner_hash,
            ResumeProfile.deleted_at.is_(None),
            ResumeProfile.expires_at > now,
        )
    )


def delete_profile(
    session: Session,
    *,
    profile_id: UUID,
    owner_hash: str,
    now: datetime,
) -> bool:
    profile = session.scalar(
        select(ResumeProfile)
        .where(
            ResumeProfile.id == profile_id,
            ResumeProfile.owner_hash == owner_hash,
        )
        .with_for_update()
    )
    if profile is None:
        return False
    if profile.deleted_at is None:
        profile.deleted_at = now
        session.flush()
    return True
