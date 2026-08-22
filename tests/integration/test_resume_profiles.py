from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from devradar.matching.resume_profile_parser import ResumeProfileDraft
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


class MissingModule(ModuleType):
    def __getattr__(self, name: str) -> object:
        pytest.fail(f"resume profile persistence is not implemented: missing {name}")


@pytest.fixture
def profile_models() -> ModuleType:
    try:
        return importlib.import_module("devradar.matching.models")
    except ModuleNotFoundError:
        return MissingModule("devradar.matching.models")


@pytest.fixture
def profile_store() -> ModuleType:
    try:
        return importlib.import_module("devradar.matching.resume_profiles")
    except ModuleNotFoundError:
        return MissingModule("devradar.matching.resume_profiles")


@pytest.fixture
def profile_engine(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _draft(content_hash: str = "b" * 64) -> ResumeProfileDraft:
    return ResumeProfileDraft(
        file_name_sanitized="profile.pdf",
        content_hash=content_hash,
        source_format="pdf",
        parser_version="resume-profile-parser-v1",
        skills=("fastapi", "postgresql", "python"),
        roles=("backend",),
        locations=("Ho Chi Minh City",),
        experience_years=Decimal("3"),
        extraction_status="accepted",
    )


def _owner(value: str) -> str:
    return sha256(value.encode()).hexdigest()


@pytest.mark.postgresql
def test_resume_profile_migration_has_bounded_constraints_and_round_trips(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(fresh_postgresql_url)
    inspector = inspect(engine)
    try:
        assert "resume_profiles" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("resume_profiles")}
        assert "raw_text" not in columns
        assert "raw_file" not in columns
        check_names = {
            check["name"] for check in inspector.get_check_constraints("resume_profiles")
        }
        assert {
            "ck_resume_profiles_owner_hash",
            "ck_resume_profiles_content_hash",
            "ck_resume_profiles_source_format",
            "ck_resume_profiles_extraction_status",
            "ck_resume_profiles_retention_mode",
            "ck_resume_profiles_expires_after_creation",
            "ck_resume_profiles_structured_arrays",
        } <= check_names
        index_names = {index["name"] for index in inspector.get_indexes("resume_profiles")}
        assert {
            "uq_resume_profiles_active_replay",
            "ix_resume_profiles_owner_expiry",
        } <= index_names
    finally:
        engine.dispose()

    command.downgrade(config, "a1d4e7f9b203")
    downgraded_engine = create_engine(fresh_postgresql_url)
    try:
        assert "resume_profiles" not in inspect(downgraded_engine).get_table_names()
    finally:
        downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.postgresql
def test_replay_reuses_one_active_profile(
    profile_engine: Engine,
    profile_models: ModuleType,
    profile_store: ModuleType,
) -> None:
    now = datetime(2026, 8, 22, 12, tzinfo=UTC)
    with Session(profile_engine) as session:
        first = profile_store.create_or_reuse_profile(
            session,
            owner_hash=_owner("owner-one"),
            draft=_draft(),
            now=now,
        )
        session.commit()
        second = profile_store.create_or_reuse_profile(
            session,
            owner_hash=_owner("owner-one"),
            draft=_draft(),
            now=now + timedelta(minutes=5),
        )
        session.commit()

        assert first.reused is False
        assert second.reused is True
        assert second.profile.id == first.profile.id
        assert session.scalar(select(func.count()).select_from(profile_models.ResumeProfile)) == 1
        assert second.profile.expires_at == now + timedelta(hours=24)


@pytest.mark.postgresql
def test_owner_scope_hides_another_owners_profile(
    profile_engine: Engine,
    profile_store: ModuleType,
) -> None:
    now = datetime(2026, 8, 22, 12, tzinfo=UTC)
    owner_one = _owner("owner-one")
    owner_two = _owner("owner-two")
    with Session(profile_engine) as session:
        first = profile_store.create_or_reuse_profile(
            session,
            owner_hash=owner_one,
            draft=_draft(),
            now=now,
        )
        second = profile_store.create_or_reuse_profile(
            session,
            owner_hash=owner_two,
            draft=_draft(),
            now=now,
        )
        session.commit()

        assert first.profile.id != second.profile.id
        assert (
            profile_store.get_active_profile(
                session,
                profile_id=first.profile.id,
                owner_hash=owner_two,
                now=now,
            )
            is None
        )


@pytest.mark.postgresql
def test_expired_replay_tombstones_old_row_and_creates_fresh_profile(
    profile_engine: Engine,
    profile_models: ModuleType,
    profile_store: ModuleType,
) -> None:
    created_at = datetime(2026, 8, 22, 12, tzinfo=UTC)
    replayed_at = created_at + timedelta(hours=25)
    owner_hash = _owner("owner-one")
    with Session(profile_engine) as session:
        first = profile_store.create_or_reuse_profile(
            session,
            owner_hash=owner_hash,
            draft=_draft(),
            now=created_at,
        )
        session.commit()
        second = profile_store.create_or_reuse_profile(
            session,
            owner_hash=owner_hash,
            draft=_draft(),
            now=replayed_at,
        )
        session.commit()

        assert second.reused is False
        assert second.profile.id != first.profile.id
        expired = session.get(profile_models.ResumeProfile, first.profile.id)
        assert expired is not None
        assert expired.deleted_at == replayed_at
        assert second.profile.expires_at == replayed_at + timedelta(hours=24)


@pytest.mark.postgresql
def test_delete_is_owner_scoped_idempotent_and_removes_active_visibility(
    profile_engine: Engine,
    profile_store: ModuleType,
) -> None:
    now = datetime(2026, 8, 22, 12, tzinfo=UTC)
    owner_hash = _owner("owner-one")
    with Session(profile_engine) as session:
        created = profile_store.create_or_reuse_profile(
            session,
            owner_hash=owner_hash,
            draft=_draft(),
            now=now,
        )
        session.commit()

        assert (
            profile_store.delete_profile(
                session,
                profile_id=created.profile.id,
                owner_hash=_owner("owner-two"),
                now=now,
            )
            is False
        )
        assert (
            profile_store.delete_profile(
                session,
                profile_id=created.profile.id,
                owner_hash=owner_hash,
                now=now,
            )
            is True
        )
        session.commit()
        assert (
            profile_store.delete_profile(
                session,
                profile_id=created.profile.id,
                owner_hash=owner_hash,
                now=now + timedelta(minutes=1),
            )
            is True
        )
        assert (
            profile_store.get_active_profile(
                session,
                profile_id=created.profile.id,
                owner_hash=owner_hash,
                now=now,
            )
            is None
        )
