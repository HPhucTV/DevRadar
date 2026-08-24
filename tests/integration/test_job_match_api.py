from __future__ import annotations

from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from devradar.catalog.models import Job
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.main import app
from devradar.matching.models import JobMatch
from devradar.platform.database import DATABASE_URL_ENV, _database_engine
from integration.test_job_match_generation import _seed

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OWNER_TOKEN = "api-owner-local-token-0123456789abcdef"
OWNER_HEADER = "X-DevRadar-Owner"


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls = 0

    def embed_passage(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        assert "private-profile.pdf" not in text
        return tuple([1.0] + [0.0] * 383)


@pytest.fixture
def match_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, str, FakeEmbeddingModel]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_CV_LOCAL_ENABLED", "true")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        profile, _ = _seed(session)
        owner_hash = sha256(OWNER_TOKEN.encode()).hexdigest()
        profile.owner_hash = owner_hash
        session.commit()
        profile_id = str(profile.id)
    engine.dispose()
    fake = FakeEmbeddingModel()
    monkeypatch.setattr("devradar.api.job_matches.get_local_embedding_model", lambda: fake)
    with TestClient(app) as client:
        yield client, fresh_postgresql_url, profile_id, fake
    _database_engine(fresh_postgresql_url).dispose()
    _database_engine.cache_clear()


@pytest.mark.postgresql
def test_job_match_routes_openapi_and_owner_contract() -> None:
    with TestClient(app) as client:
        document = client.get("/api/v1/openapi.json").json()

    post = document["paths"]["/api/v1/resume-profiles/{profileId}/matches"]["post"]
    get = document["paths"]["/api/v1/resume-profiles/{profileId}/matches"]["get"]
    assert "requestBody" not in post
    for operation in (post, get):
        owner_parameters = [
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "header" and parameter["name"] == OWNER_HEADER
        ]
        assert len(owner_parameters) == 1
        assert owner_parameters[0]["required"] is True


@pytest.mark.postgresql
def test_generate_replay_get_pagination_and_min_score(
    match_api: tuple[TestClient, str, str, FakeEmbeddingModel],
) -> None:
    client, database_url, profile_id, fake = match_api
    headers = {OWNER_HEADER: OWNER_TOKEN}
    generated = client.post(f"/api/v1/resume-profiles/{profile_id}/matches", headers=headers)
    replay = client.post(f"/api/v1/resume-profiles/{profile_id}/matches", headers=headers)
    listed = client.get(
        f"/api/v1/resume-profiles/{profile_id}/matches?page=1&pageSize=1&minScore=0.5",
        headers=headers,
    )

    assert generated.status_code == 200
    assert generated.json()["data"]["scoringVersion"] == "job-match-scoring-v2"
    assert generated.json()["data"]["storedMatches"] == 1
    assert generated.json()["data"]["createdMatches"] == 1
    assert replay.status_code == 200
    assert replay.json()["data"]["reusedMatches"] == 1
    assert listed.status_code == 200
    assert listed.json()["pagination"] == {
        "page": 1,
        "pageSize": 1,
        "totalItems": 1,
        "totalPages": 1,
    }
    item = listed.json()["data"][0]
    assert set(item) == {
        "id",
        "jobId",
        "overallScore",
        "evidenceCoverage",
        "components",
        "matchedSkills",
        "missingSkills",
        "explanation",
        "scoringVersion",
        "embeddingModel",
        "embeddingRevision",
        "createdAt",
        "job",
    }
    assert "contentHash" not in listed.text
    assert "ownerHash" not in listed.text
    assert '"embedding":' not in listed.text.casefold()
    assert fake.calls == 2
    del database_url


@pytest.mark.postgresql
def test_match_list_hides_rows_when_job_source_is_not_globally_approved(
    match_api: tuple[TestClient, str, str, FakeEmbeddingModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database_url, profile_id, _ = match_api
    headers = {OWNER_HEADER: OWNER_TOKEN}
    assert client.post(f"/api/v1/resume-profiles/{profile_id}/matches", headers=headers).is_success

    engine = create_engine(database_url)
    with Session(engine) as session:
        source = session.scalar(
            select(Source)
            .join(Job, Job.source_id == Source.id)
            .join(JobMatch, JobMatch.job_id == Job.id)
            .where(JobMatch.resume_profile_id == UUID(profile_id))
        )
        assert source is not None
        source.approval_status = SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
        session.commit()
    engine.dispose()

    listed = client.get(f"/api/v1/resume-profiles/{profile_id}/matches", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"] == []
    assert listed.json()["pagination"]["totalItems"] == 0

    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    local_listed = client.get(
        f"/api/v1/resume-profiles/{profile_id}/matches",
        headers=headers,
    )
    assert local_listed.json()["pagination"]["totalItems"] == 1


@pytest.mark.postgresql
def test_match_api_fail_closed_gate_owner_model_and_unknown_query(
    match_api: tuple[TestClient, str, str, FakeEmbeddingModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, profile_id, _ = match_api
    headers = {OWNER_HEADER: OWNER_TOKEN}
    monkeypatch.setenv("DEVRADAR_CV_LOCAL_ENABLED", "false")
    gated = client.post(f"/api/v1/resume-profiles/{profile_id}/matches", headers=headers)
    assert gated.status_code == 403
    assert gated.json()["error"]["code"] == "cv_local_disabled"

    monkeypatch.setenv("DEVRADAR_CV_LOCAL_ENABLED", "true")
    wrong_owner = client.get(
        f"/api/v1/resume-profiles/{profile_id}/matches",
        headers={OWNER_HEADER: "other-owner-local-token-0123456789abcdef"},
    )
    assert wrong_owner.status_code == 404

    unknown = client.get(
        f"/api/v1/resume-profiles/{profile_id}/matches?model=other",
        headers=headers,
    )
    assert unknown.status_code == 422

    class Unavailable:
        def embed_passage(self, _text: str) -> tuple[float, ...]:
            from devradar.intelligence.embeddings import EmbeddingModelUnavailable

            raise EmbeddingModelUnavailable

    monkeypatch.setattr("devradar.api.job_matches.get_local_embedding_model", Unavailable)
    wrong_owner_post = client.post(
        f"/api/v1/resume-profiles/{profile_id}/matches",
        headers={OWNER_HEADER: "other-owner-local-token-0123456789abcdef"},
    )
    assert wrong_owner_post.status_code == 404
    unavailable = client.post(f"/api/v1/resume-profiles/{profile_id}/matches", headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "embedding_model_unavailable"


@pytest.mark.postgresql
def test_match_api_default_disabled_without_database_or_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVRADAR_CV_LOCAL_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/resume-profiles/00000000-0000-0000-0000-000000000000/matches",
            headers={OWNER_HEADER: OWNER_TOKEN},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cv_local_disabled"
