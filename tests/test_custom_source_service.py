from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from devradar.api.errors import ApiContractError
from devradar.custom_sources.models import CustomSourceProfileDraft, CustomSourceStatus
from devradar.custom_sources.parser import (
    CustomCandidate,
    CustomFieldProvenance,
    CustomParseResult,
)
from devradar.custom_sources.service import (
    CustomSourceServiceError,
    create_profile,
    ensure_custom_sources_enabled,
    preview_profile,
    update_profile,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.profile: object | None = None

    def add(self, value: object) -> None:
        self.added.append(value)
        if value.__class__.__name__ == "CustomSourceProfile":
            self.profile = value

    def flush(self) -> None:
        return None

    def get(self, model: object, profile_id: UUID, **kwargs: object) -> object | None:
        del model, kwargs
        profile = self.profile
        return (
            profile if profile is not None and getattr(profile, "id", None) == profile_id else None
        )


def _draft() -> CustomSourceProfileDraft:
    return CustomSourceProfileDraft.from_input(
        name="Example",
        base_url="https://example.test/jobs",
        permission_acknowledged=True,
    )


def test_feature_flag_blocks_custom_source_api_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", raising=False)
    with pytest.raises(ApiContractError) as captured:
        ensure_custom_sources_enabled()
    assert captured.value.code == "custom_sources_disabled"


def test_create_profile_is_owner_scoped_and_starts_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    owner_id = uuid4()
    profile = create_profile(session, owner_user_id=owner_id, draft=_draft())  # type: ignore[arg-type]
    assert profile.owner_user_id == owner_id
    assert profile.status is CustomSourceStatus.DRAFT
    assert profile.source_id is not None
    assert profile.permission_acknowledged_at.tzinfo is not None
    assert len(session.added) == 2


def test_preview_does_not_create_job_missing_removed_or_change_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    profile = create_profile(session, owner_user_id=uuid4(), draft=_draft())  # type: ignore[arg-type]
    before = len(session.added)
    result = preview_profile(
        session,  # type: ignore[arg-type]
        owner_user_id=profile.owner_user_id,
        profile_id=profile.id,
        runner=lambda current: CustomParseResult(
            candidates=(
                CustomCandidate(
                    external_id="1",
                    job_url="https://example.test/jobs/1",
                    title="Backend",
                    company="Example",
                    provenance=(CustomFieldProvenance("title", "mapping:.title", "mapping"),),
                    confidence=0.8,
                ),
            )
        ),
    )
    assert result.candidates[0].external_id == "1"
    assert profile.status is CustomSourceStatus.PREVIEW_READY
    assert len(session.added) == before
    assert not any(
        item.__class__.__name__ in {"Job", "JobChange", "CrawlRun"} for item in session.added
    )


def test_cross_owner_profile_id_returns_not_found_without_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    profile = create_profile(session, owner_user_id=uuid4(), draft=_draft())  # type: ignore[arg-type]
    with pytest.raises(CustomSourceServiceError) as captured:
        preview_profile(
            session,  # type: ignore[arg-type]
            owner_user_id=uuid4(),
            profile_id=profile.id,
            runner=lambda current: CustomParseResult(),
        )
    assert captured.value.code == "profile_not_found"
    assert "Example" not in str(captured.value)


def test_arbitrary_url_field_and_unapproved_status_transition_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    profile = create_profile(session, owner_user_id=uuid4(), draft=_draft())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CustomSourceProfileDraft.from_input(
            name="Example",
            base_url="https://example.test/jobs",
            permission_acknowledged=True,
            allowed_path_prefixes=["/jobs", "https://attacker.test"],
        )
    with pytest.raises(CustomSourceServiceError, match="preview"):
        update_profile(
            session,  # type: ignore[arg-type]
            owner_user_id=profile.owner_user_id,
            profile_id=profile.id,
            status=CustomSourceStatus.ENABLED,
        )


def test_paused_profile_can_resume_after_a_successful_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    profile = create_profile(session, owner_user_id=uuid4(), draft=_draft())  # type: ignore[arg-type]
    preview_profile(
        session,  # type: ignore[arg-type]
        owner_user_id=profile.owner_user_id,
        profile_id=profile.id,
        runner=lambda current: CustomParseResult(
            candidates=(
                CustomCandidate(
                    external_id="1",
                    job_url="https://example.test/jobs/1",
                    title="Backend",
                    company="Example",
                    provenance=(CustomFieldProvenance("title", "html:heading", "html"),),
                    confidence=0.8,
                ),
            )
        ),
    )
    update_profile(
        session,  # type: ignore[arg-type]
        owner_user_id=profile.owner_user_id,
        profile_id=profile.id,
        status=CustomSourceStatus.ENABLED,
    )
    update_profile(
        session,  # type: ignore[arg-type]
        owner_user_id=profile.owner_user_id,
        profile_id=profile.id,
        status=CustomSourceStatus.PAUSED,
    )
    update_profile(
        session,  # type: ignore[arg-type]
        owner_user_id=profile.owner_user_id,
        profile_id=profile.id,
        status=CustomSourceStatus.ENABLED,
    )
    assert profile.status is CustomSourceStatus.ENABLED


@pytest.mark.parametrize(
    ("current_status", "expected_code"),
    [
        (CustomSourceStatus.DRAFT, "preview_required"),
        (CustomSourceStatus.BLOCKED, "preview_required"),
        (CustomSourceStatus.RETIRED, "profile_retired"),
    ],
)
def test_invalid_state_cannot_use_pause_to_bypass_preview_gate(
    monkeypatch: pytest.MonkeyPatch,
    current_status: CustomSourceStatus,
    expected_code: str,
) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    profile = create_profile(session, owner_user_id=uuid4(), draft=_draft())  # type: ignore[arg-type]
    profile.status = current_status
    if current_status is CustomSourceStatus.BLOCKED:
        profile.block_reason = "permission_required"

    with pytest.raises(CustomSourceServiceError) as captured:
        update_profile(
            session,  # type: ignore[arg-type]
            owner_user_id=profile.owner_user_id,
            profile_id=profile.id,
            status=CustomSourceStatus.PAUSED,
        )

    assert captured.value.code == expected_code
    assert profile.status is current_status


def test_owner_cannot_set_workflow_managed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    session = FakeSession()
    profile = create_profile(session, owner_user_id=uuid4(), draft=_draft())  # type: ignore[arg-type]

    with pytest.raises(CustomSourceServiceError, match="controlled"):
        update_profile(
            session,  # type: ignore[arg-type]
            owner_user_id=profile.owner_user_id,
            profile_id=profile.id,
            status=CustomSourceStatus.PREVIEW_READY,
        )
