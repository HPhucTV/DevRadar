from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.postgresql
def test_source_recipe_schema_has_bounded_persistence_contract(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        inspector = inspect(engine)
        assert {"source_recipes", "source_recipe_previews"} <= set(inspector.get_table_names())
        recipe_columns_by_name = {
            column["name"]: column for column in inspector.get_columns("source_recipes")
        }
        recipe_columns = set(recipe_columns_by_name)
        assert {
            "id",
            "owner_user_id",
            "source_id",
            "name",
            "status",
            "listing_url",
            "origin",
            "allowed_hosts",
            "allowed_path_prefixes",
            "terms_notice",
            "terms_notice_version",
            "terms_evidence_url",
            "terms_acknowledged_at",
            "seniority_filter",
            "schedule_kind",
            "schedule_local_time",
            "schedule_weekday",
            "timezone",
            "next_run_at",
            "field_mapping",
            "pagination_mapping",
            "latest_successful_preview_id",
            "config_version",
            "block_reason",
            "cooldown_until",
            "item_budget",
            "page_budget",
            "request_budget",
            "byte_budget",
            "time_budget_seconds",
            "requests_per_minute",
            "created_at",
            "updated_at",
            "last_used_at",
        } <= recipe_columns
        last_used_at = recipe_columns_by_name["last_used_at"]
        assert last_used_at["nullable"] is True
        assert getattr(last_used_at["type"], "timezone", False) is True
        preview_columns = {
            column["name"] for column in inspector.get_columns("source_recipe_previews")
        }
        assert {
            "id",
            "recipe_id",
            "status",
            "config_hash",
            "candidate_jobs",
            "warnings",
            "element_map",
            "screenshot",
            "screenshot_media_type",
            "error_code",
            "requested_at",
            "started_at",
            "finished_at",
            "expires_at",
        } <= preview_columns
        crawl_columns = {column["name"] for column in inspector.get_columns("crawl_runs")}
        assert "items_filtered_out" in crawl_columns

        recipe_checks = {
            constraint["name"] for constraint in inspector.get_check_constraints("source_recipes")
        }
        assert {
            "ck_source_recipes_status",
            "ck_source_recipes_terms_notice",
            "ck_source_recipes_schedule",
            "ck_source_recipes_budgets",
            "ck_source_recipes_seniority_filter",
            "ck_source_recipes_https_listing_url",
        } <= recipe_checks
        preview_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("source_recipe_previews")
        }
        assert {
            "ck_source_recipe_previews_status",
            "ck_source_recipe_previews_payloads",
            "ck_source_recipe_previews_screenshot_size",
            "ck_source_recipe_previews_expiry",
        } <= preview_checks
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_source_recipe_last_used_migration_round_trip(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    engine = create_engine(fresh_postgresql_url)
    try:
        command.upgrade(config, "c5d7e9f1a3b2")
        assert "last_used_at" not in {
            column["name"] for column in inspect(engine).get_columns("source_recipes")
        }

        command.upgrade(config, "e8f2a4c6d901")
        assert "last_used_at" in {
            column["name"] for column in inspect(engine).get_columns("source_recipes")
        }

        command.downgrade(config, "c5d7e9f1a3b2")
        assert "last_used_at" not in {
            column["name"] for column in inspect(engine).get_columns("source_recipes")
        }

        command.upgrade(config, "e8f2a4c6d901")
        assert "last_used_at" in {
            column["name"] for column in inspect(engine).get_columns("source_recipes")
        }
    finally:
        engine.dispose()
