from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date

import pytest

from devradar.ingestion.models import SourceApprovalStatus
from devradar.ingestion.source_registry import (
    DiscoveryMode,
    FetchPolicy,
    IdentityStrategy,
    PolicyReview,
    PolicyScope,
    SourceConfig,
)


def _policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=("example.test",),
        allowed_path_prefixes=("/jobs",),
        content_types=("text/html", "application/json"),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=2_000_000,
        requests_per_minute=2,
    )


def _config() -> SourceConfig:
    return SourceConfig(
        source_key="recipe-fixture",
        name="Recipe fixture",
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        base_url="https://example.test/jobs",
        adapter_key="source_recipe",
        discovery_mode=DiscoveryMode.SERVER_RENDERED_HTML,
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        external_id_field="external_id",
        expected_pagination="mapped_or_single_page",
        fetch_policy=_policy(),
        policy_review=PolicyReview(
            scope=PolicyScope.PERMISSION_REQUIRED,
            robots_reviewed_at=date(2026, 8, 24),
            terms_reviewed_at=date(2026, 8, 24),
            next_review_at=date(2026, 11, 24),
        ),
        config_version="recipe-config-v1",
    )


def test_source_recipe_config_is_bounded_and_immutable() -> None:
    config = _config()

    assert config.fetch_policy.allowed_hosts == ("example.test",)
    assert config.fetch_policy.allowed_path_prefixes == ("/jobs",)
    assert config.approval_status is SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
    with pytest.raises(TypeError):
        config.adapter_settings["new"] = "value"  # type: ignore[index]


@pytest.mark.parametrize(
    "update",
    (
        lambda config: replace(config, source_key="https://example.test/jobs"),
        lambda config: replace(config, adapter_key="package.module:Adapter"),
        lambda config: replace(config, base_url="https://127.0.0.1/jobs"),
    ),
)
def test_source_recipe_config_rejects_unsafe_identity(
    update: Callable[[SourceConfig], SourceConfig],
) -> None:
    with pytest.raises(ValueError):
        update(_config())


def test_fetch_policy_requires_throttle_and_public_host_boundary() -> None:
    with pytest.raises(ValueError, match="throttle"):
        replace(_policy(), requests_per_minute=None)
    with pytest.raises(ValueError, match="hostnames"):
        replace(_policy(), allowed_hosts=("127.0.0.1",))
