from __future__ import annotations

import re

from fastapi.testclient import TestClient

from devradar.main import app

client = TestClient(app)


def test_privacy_policy_is_explicit_and_secret_free() -> None:
    response = client.get("/api/v1/privacy")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "policyVersion": "privacy-v3",
            "sourceRecipesLocalOnly": True,
            "accessControlBypassAllowed": False,
            "rawCvFileRetained": False,
            "resumeProfileTtlHours": 24,
            "externalLlmCvJdAllowed": False,
        }
    }
    assert not re.search(r"password|secret|webhook|rawJd|databaseUrl", response.text, re.I)


def test_privacy_policy_is_in_openapi_contract() -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/privacy" in response.json()["paths"]
