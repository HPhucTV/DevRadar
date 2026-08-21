from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

import pytest

from devradar.ingestion.contracts import (
    FetchResult,
    JobSourceAdapter,
    ListingRef,
    ParsedJob,
    ParseFailure,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.models import SourceApprovalStatus
from devradar.ingestion.source_registry import (
    V1_SOURCE_CONFIGS,
    V1_SOURCE_REGISTRY,
    AdapterNotRegisteredError,
    AdapterRegistry,
    FetchPolicy,
    IdentityStrategy,
    PolicyReview,
    PolicyScope,
    SourceNotApprovedError,
    SourceRegistry,
    UnknownSourceError,
)


class StubAdapter(JobSourceAdapter):
    def __init__(self, adapter_key: str) -> None:
        self.adapter_key = adapter_key
        self.adapter_version = "stub-v1"

    def discover(self, run_context: RunContext) -> Iterable[ListingRef]:
        return ()

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        raise AssertionError("fetch is outside this registry contract test")

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        return ParseFailure(
            error_code="not_implemented",
            stage="parse",
            safe_summary="Stub adapter does not parse fixtures.",
        )


def _all_stub_adapters() -> AdapterRegistry:
    return AdapterRegistry(StubAdapter(config.adapter_key) for config in V1_SOURCE_CONFIGS)


def test_v1_registry_contains_only_three_approved_sources() -> None:
    assert V1_SOURCE_REGISTRY.keys() == (
        "momo-careers",
        "naver-vietnam-greenhouse",
        "vng-careers",
    )
    assert all(
        config.approval_status is SourceApprovalStatus.APPROVED for config in V1_SOURCE_CONFIGS
    )
    assert all(
        config.identity_strategy is IdentityStrategy.EXTERNAL_ID for config in V1_SOURCE_CONFIGS
    )
    assert "geocomply-lever" not in V1_SOURCE_REGISTRY.keys()


@pytest.mark.parametrize("source_key", V1_SOURCE_REGISTRY.keys())
def test_approved_source_resolves_only_to_registered_adapter(source_key: str) -> None:
    resolved = V1_SOURCE_REGISTRY.resolve(source_key, _all_stub_adapters())
    assert resolved.config.source_key == source_key
    assert resolved.adapter.adapter_key == resolved.config.adapter_key


def test_candidate_source_is_rejected_even_when_adapter_exists() -> None:
    approved = V1_SOURCE_CONFIGS[0]
    candidate = replace(
        approved,
        source_key="permission-required-source",
        approval_status=SourceApprovalStatus.CANDIDATE,
        policy_review=PolicyReview(
            scope=PolicyScope.PERMISSION_REQUIRED,
            robots_reviewed_at=approved.policy_review.robots_reviewed_at,
            terms_reviewed_at=approved.policy_review.terms_reviewed_at,
            next_review_at=approved.policy_review.next_review_at,
        ),
    )
    registry = SourceRegistry((candidate,))
    adapters = AdapterRegistry((StubAdapter(candidate.adapter_key),))

    with pytest.raises(SourceNotApprovedError) as captured:
        registry.resolve(candidate.source_key, adapters)

    assert captured.value.code == "source_not_approved"


def test_unknown_source_and_unregistered_adapter_fail_closed() -> None:
    with pytest.raises(UnknownSourceError) as unknown:
        V1_SOURCE_REGISTRY.resolve("https://attacker.test/jobs", _all_stub_adapters())
    assert unknown.value.code == "source_not_found"

    with pytest.raises(AdapterNotRegisteredError) as missing:
        V1_SOURCE_REGISTRY.resolve("vng-careers", AdapterRegistry())
    assert missing.value.code == "adapter_not_registered"


def test_arbitrary_adapter_path_is_not_a_valid_config_key() -> None:
    with pytest.raises(ValueError, match="adapter_key"):
        replace(V1_SOURCE_CONFIGS[0], adapter_key="package.module:Adapter")


def test_source_fetch_boundaries_match_approval_records() -> None:
    by_key = {config.source_key: config for config in V1_SOURCE_CONFIGS}

    vng = by_key["vng-careers"]
    assert vng.fetch_policy.allowed_hosts == ("career.vng.com.vn",)
    assert vng.fetch_policy.requests_per_minute == 6
    vng_group_ids = vng.adapter_settings["job_group_ids"]
    vng_group_names = vng.adapter_settings["job_families"]
    assert tuple(zip(vng_group_ids, vng_group_names, strict=True)) == (
        ("385", "Software"),
        ("423", "System"),
        ("384", "QC/P-QA"),
        ("387", "Tech Management"),
        ("457", "Data Engineering"),
        ("462", "Data Science"),
        ("464", "Business Analysis"),
        ("465", "Artificial Intelligence"),
    )

    naver = by_key["naver-vietnam-greenhouse"]
    assert naver.adapter_settings["board_token"] == "navervietnam"
    assert naver.reference_hosts == ("job-boards.greenhouse.io",)
    assert "job-boards.greenhouse.io" not in naver.fetch_policy.allowed_hosts

    momo = by_key["momo-careers"]
    assert momo.adapter_settings["division_group_id"] == "DGM.0001"
    assert momo.fetch_policy.browser_network_hosts == ("aws.momo.vn",)
    assert momo.fetch_policy.minimum_action_interval_seconds == 5
