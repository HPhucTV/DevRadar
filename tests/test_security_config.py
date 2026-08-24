from __future__ import annotations

import pytest

import devradar.platform.security_config as security_config
from devradar.platform.security_config import (
    SecurityConfigurationError,
    validate_security_configuration,
)


def test_localhost_service_defaults_are_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVRADAR_DEPLOYMENT_CLASS", raising=False)
    monkeypatch.delenv("DEVRADAR_SECRET_SOURCE", raising=False)

    assert validate_security_configuration() == "LOCALHOST_SERVICE"


def test_protected_deployment_requires_session_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "PROTECTED")
    monkeypatch.setenv("DEVRADAR_SECRET_SOURCE", "managed")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "false")

    with pytest.raises(SecurityConfigurationError, match="deployment_auth_required"):
        validate_security_configuration()


def test_public_deployment_rejects_insecure_or_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "PUBLIC")
    monkeypatch.setenv("DEVRADAR_SECRET_SOURCE", "managed")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_OPERATOR_PASSWORD_HASH", "pbkdf2_sha256$placeholder")
    monkeypatch.setenv("DEVRADAR_AUTH_COOKIE_SECURE", "false")

    with pytest.raises(SecurityConfigurationError, match="secure_cookie_required"):
        validate_security_configuration()

    monkeypatch.setenv("DEVRADAR_AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("DEVRADAR_ALLOWED_ORIGINS", "*")
    with pytest.raises(SecurityConfigurationError, match="wildcard_origin_forbidden"):
        validate_security_configuration()

    monkeypatch.setenv("DEVRADAR_ALLOWED_ORIGINS", "https://devradar.example")
    with pytest.raises(SecurityConfigurationError, match="local_database_secret_forbidden"):
        validate_security_configuration(
            "postgresql+psycopg://devradar:devradar_local_only@database:5432/devradar"
        )


def test_source_recipes_flag_is_explicit_and_localhost_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_recipes_local_enabled = security_config.source_recipes_local_enabled
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.delenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", raising=False)
    assert source_recipes_local_enabled() is False

    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", " TRUE ")
    assert source_recipes_local_enabled() is True

    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "yes")
    assert source_recipes_local_enabled() is False

    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "PROTECTED")
    assert source_recipes_local_enabled() is False


@pytest.mark.parametrize("deployment", ["PROTECTED", "PUBLIC"])
def test_source_recipes_are_rejected_outside_localhost(
    monkeypatch: pytest.MonkeyPatch,
    deployment: str,
) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", deployment)
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")

    with pytest.raises(SecurityConfigurationError, match="source_recipes_non_local_forbidden"):
        validate_security_configuration()


def test_local_no_login_flag_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    assert hasattr(security_config, "local_no_login_enabled")
    local_no_login_enabled = security_config.local_no_login_enabled
    monkeypatch.delenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", raising=False)
    assert local_no_login_enabled() is False

    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", " TRUE ")
    assert local_no_login_enabled() is True

    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "yes")
    assert local_no_login_enabled() is False


@pytest.mark.parametrize("deployment", ["PROTECTED", "PUBLIC"])
def test_local_no_login_is_rejected_outside_localhost(
    monkeypatch: pytest.MonkeyPatch,
    deployment: str,
) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", deployment)
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "false")

    with pytest.raises(SecurityConfigurationError, match="local_no_login_forbidden"):
        validate_security_configuration()


def test_local_no_login_is_rejected_with_session_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_LOCAL_NO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_AUTH_ENABLED", "true")

    with pytest.raises(SecurityConfigurationError, match="local_no_login_auth_conflict"):
        validate_security_configuration()
