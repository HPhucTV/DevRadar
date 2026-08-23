from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.auth.models import User
from devradar.custom_sources.models import (
    CustomParserMode,
    CustomScheduleKind,
    CustomSourceProfile,
    CustomSourceStatus,
)
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.mark.postgresql
def test_custom_source_profile_schema_enforces_owner_and_schedule(
    fresh_postgresql_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        assert "custom_source_profiles" in inspect(engine).get_table_names()
        now = datetime.now(UTC)
        with Session(engine) as session:
            user = User(
                username=f"owner{uuid4().hex[:8]}",
                password_hash="x" * 64,
            )
            source = Source(
                name=f"Custom {uuid4().hex[:8]}",
                base_url="https://example.test/jobs",
                adapter_key="custom_source",
                approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
                rate_limit_policy={"requests_per_minute": 2, "concurrency": 1},
                allowed_hosts=["example.test"],
            )
            session.add_all([user, source])
            session.flush()
            profile = CustomSourceProfile(
                source_id=source.id,
                owner_user_id=user.id,
                name="Example profile",
                status=CustomSourceStatus.DRAFT,
                base_url="https://example.test/jobs",
                allowed_hosts=["example.test"],
                allowed_path_prefixes=["/jobs"],
                parser_mode=CustomParserMode.AUTO,
                field_mapping={},
                schedule_kind=CustomScheduleKind.DAILY_AT,
                daily_at=time(9, 0),
                timezone="Asia/Ho_Chi_Minh",
                page_budget=10,
                item_budget=500,
                byte_budget=2_000_000,
                requests_per_minute=2,
                permission_acknowledged_at=now,
            )
            session.add(profile)
            session.commit()

            invalid_schedule = CustomSourceProfile(
                source_id=source.id,
                owner_user_id=user.id,
                name="Invalid schedule",
                status=CustomSourceStatus.DRAFT,
                base_url="https://example.test/jobs",
                allowed_hosts=["example.test"],
                allowed_path_prefixes=["/jobs"],
                parser_mode=CustomParserMode.AUTO,
                field_mapping={},
                schedule_kind=CustomScheduleKind.INTERVAL,
                interval_minutes=None,
                daily_at=time(9, 0),
                timezone="Asia/Ho_Chi_Minh",
                page_budget=10,
                item_budget=500,
                byte_budget=2_000_000,
                requests_per_minute=2,
                permission_acknowledged_at=now,
            )
            session.add(invalid_schedule)
            with pytest.raises(IntegrityError, match="ck_custom_source_profiles_schedule_boundary"):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()
