from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "f1a3c5e7b902"
TARGET_REVISION = "a2c4e6f8b103"


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.mark.postgresql
def test_parser_v2_migration_invalidates_active_work_and_requires_preview(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    (
        owner_id,
        source_id,
        recipe_id,
        retired_id,
        blocked_id,
        succeeded_preview_id,
        pending_preview_id,
    ) = (uuid4() for _ in range(7))
    pending_run_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO auth_users (id, username, password_hash) "
                    "VALUES (:id, 'parser-v2-owner', :password_hash)"
                ),
                {"id": owner_id, "password_hash": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO sources (id, name, base_url, adapter_key, approval_status, "
                    "rate_limit_policy, allowed_hosts) VALUES "
                    "(:id, 'Parser v2 source', 'https://jobs.example.test', 'source_recipe', "
                    "'owner_authorized_local', CAST(:rate AS jsonb), CAST(:hosts AS jsonb))"
                ),
                {
                    "id": source_id,
                    "rate": '{"requests_per_minute":2}',
                    "hosts": '["jobs.example.test"]',
                },
            )
            connection.execute(
                text(
                    "INSERT INTO source_recipes (id, owner_user_id, source_id, name, status, "
                    "listing_url, origin, allowed_hosts, allowed_path_prefixes, parser_version, "
                    "field_mapping, pagination_mapping, seniority_filter, config_version, "
                    "schedule_kind, schedule_local_time, timezone, next_run_at, created_at, "
                    "updated_at, block_reason, cooldown_until) VALUES "
                    "(:id, :owner_id, :source_id, 'Enabled recipe', 'enabled', "
                    "'https://jobs.example.test/list', 'https://jobs.example.test', "
                    "CAST(:hosts AS jsonb), CAST(:paths AS jsonb), 'source-recipe-parser-v1', "
                    "'{}'::jsonb, '{}'::jsonb, '[\"all\"]'::jsonb, 'legacy-config', "
                    "'daily', '09:00', 'Asia/Ho_Chi_Minh', :next_run_at, :now, :now, NULL, NULL), "
                    "(:retired_id, :owner_id, NULL, 'Retired recipe', 'retired', "
                    "'https://jobs.example.test/retired', 'https://jobs.example.test', "
                    "CAST(:hosts AS jsonb), CAST(:retired_paths AS jsonb), "
                    "'source-recipe-parser-v1', '{}'::jsonb, '{}'::jsonb, '[\"all\"]'::jsonb, "
                    "'legacy-retired-config', 'manual', NULL, 'Asia/Ho_Chi_Minh', NULL, "
                    ":now, :now, "
                    "NULL, NULL), "
                    "(:blocked_id, :owner_id, NULL, 'Blocked recipe', 'blocked', "
                    "'https://jobs.example.test/blocked', 'https://jobs.example.test', "
                    "CAST(:hosts AS jsonb), CAST(:blocked_paths AS jsonb), "
                    "'source-recipe-parser-v1', '{}'::jsonb, '{}'::jsonb, '[\"all\"]'::jsonb, "
                    "'legacy-blocked-config', 'manual', NULL, 'Asia/Ho_Chi_Minh', NULL, "
                    ":now, :now, "
                    "'access_denied', :cooldown_until)"
                ),
                {
                    "id": recipe_id,
                    "retired_id": retired_id,
                    "blocked_id": blocked_id,
                    "owner_id": owner_id,
                    "source_id": source_id,
                    "hosts": '["jobs.example.test"]',
                    "paths": '["/list"]',
                    "retired_paths": '["/retired"]',
                    "blocked_paths": '["/blocked"]',
                    "next_run_at": now + timedelta(hours=1),
                    "cooldown_until": now + timedelta(hours=2),
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO source_recipe_previews (id, recipe_id, status, config_hash, "
                    "candidate_jobs, warnings, element_map, requested_at, started_at, finished_at, "
                    "expires_at) VALUES "
                    "(:succeeded_id, :recipe_id, 'succeeded', :hash, "
                    "CAST(:jobs AS jsonb), '[]'::jsonb, '{}'::jsonb, :requested, :started, "
                    ":finished, :expires), "
                    "(:pending_id, :recipe_id, 'pending', :hash, '[]'::jsonb, '[]'::jsonb, "
                    "'{}'::jsonb, :requested, NULL, NULL, :expires)"
                ),
                {
                    "succeeded_id": succeeded_preview_id,
                    "pending_id": pending_preview_id,
                    "recipe_id": recipe_id,
                    "hash": "b" * 64,
                    "jobs": "[{},{},{}]",
                    "requested": now - timedelta(minutes=2),
                    "started": now - timedelta(minutes=1),
                    "finished": now,
                    "expires": now + timedelta(hours=1),
                },
            )
            connection.execute(
                text(
                    "UPDATE source_recipes SET latest_successful_preview_id = :preview_id, "
                    "latest_successful_preview_hash = :hash WHERE id = :recipe_id"
                ),
                {"preview_id": succeeded_preview_id, "hash": "c" * 64, "recipe_id": recipe_id},
            )
            connection.execute(
                text(
                    "INSERT INTO crawl_runs (id, source_id, trigger_type, status, coverage_status, "
                    "adapter_version, config_version) VALUES "
                    "(:id, :source_id, 'manual', 'pending', 'unknown', 'pending', 'legacy-config')"
                ),
                {"id": pending_run_id, "source_id": source_id},
            )

        command.upgrade(config, TARGET_REVISION)

        with engine.connect() as connection:
            recipe = connection.execute(
                text(
                    "SELECT parser_version, status, latest_successful_preview_id, "
                    "latest_successful_preview_hash, next_run_at, updated_at "
                    "FROM source_recipes WHERE id = :id"
                ),
                {"id": recipe_id},
            ).one()
            retired = connection.execute(
                text("SELECT parser_version, status FROM source_recipes WHERE id = :id"),
                {"id": retired_id},
            ).one()
            blocked = connection.execute(
                text(
                    "SELECT parser_version, status, block_reason, cooldown_until, "
                    "latest_successful_preview_id FROM source_recipes WHERE id = :id"
                ),
                {"id": blocked_id},
            ).one()
            pending_preview = connection.execute(
                text(
                    "SELECT status, error_code, started_at, finished_at "
                    "FROM source_recipe_previews WHERE id = :id"
                ),
                {"id": pending_preview_id},
            ).one()
            historical_preview_status = connection.execute(
                text("SELECT status FROM source_recipe_previews WHERE id = :id"),
                {"id": succeeded_preview_id},
            ).scalar_one()
            pending_run = connection.execute(
                text(
                    "SELECT status, coverage_status, error_code, started_at, finished_at "
                    "FROM crawl_runs WHERE id = :id"
                ),
                {"id": pending_run_id},
            ).one()

        assert tuple(recipe[:5]) == ("source-recipe-parser-v2", "draft", None, None, None)
        assert recipe.updated_at > now
        assert tuple(retired) == ("source-recipe-parser-v2", "retired")
        assert tuple(blocked[:3]) == (
            "source-recipe-parser-v2",
            "blocked",
            "access_denied",
        )
        assert blocked.cooldown_until is not None
        assert blocked.latest_successful_preview_id is None
        assert pending_preview.status == "failed"
        assert pending_preview.error_code == "parser_version_changed"
        assert pending_preview.started_at is not None and pending_preview.finished_at is not None
        assert historical_preview_status == "succeeded"
        assert pending_run.status == "cancelled"
        assert pending_run.coverage_status == "incomplete"
        assert pending_run.error_code == "source_recipe_parser_version_changed"
        assert pending_run.started_at is not None and pending_run.finished_at is not None
        parser_default = next(
            column["default"]
            for column in inspect(engine).get_columns("source_recipes")
            if column["name"] == "parser_version"
        )
        assert "source-recipe-parser-v2" in str(parser_default)

        command.downgrade(config, PREVIOUS_REVISION)
        with engine.connect() as connection:
            versions = set(
                connection.execute(text("SELECT parser_version FROM source_recipes")).scalars()
            )
        assert versions == {"source-recipe-parser-v1"}
    finally:
        engine.dispose()
