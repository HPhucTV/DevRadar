"""Fail-closed deployment and secret-source configuration checks."""

from __future__ import annotations

import os
from typing import Literal

from devradar.auth.service import allowed_origins, auth_enabled, cookie_secure, operator_bootstrap

DeploymentClass = Literal["LOCALHOST_SERVICE", "PROTECTED", "PUBLIC"]
DEPLOYMENT_CLASS_ENV = "DEVRADAR_DEPLOYMENT_CLASS"
SECRET_SOURCE_ENV = "DEVRADAR_SECRET_SOURCE"
SOURCE_RECIPES_LOCAL_ENABLED_ENV = "DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED"
LOCAL_NO_LOGIN_ENABLED_ENV = "DEVRADAR_LOCAL_NO_LOGIN_ENABLED"
LOCAL_DATABASE_MARKER = "devradar_local_only"


class SecurityConfigurationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _deployment_class() -> DeploymentClass:
    value = os.environ.get(DEPLOYMENT_CLASS_ENV, "LOCALHOST_SERVICE").strip().upper()
    if value not in {"LOCALHOST_SERVICE", "PROTECTED", "PUBLIC"}:
        raise SecurityConfigurationError("deployment_class_invalid")
    return value  # type: ignore[return-value]


def source_recipes_local_enabled() -> bool:
    """Return true only for an explicit localhost-only source recipe deployment."""

    enabled = os.environ.get(SOURCE_RECIPES_LOCAL_ENABLED_ENV, "false").strip().casefold() == "true"
    return enabled and _deployment_class() == "LOCALHOST_SERVICE"


def local_no_login_enabled() -> bool:
    """Return whether the explicit localhost-only identity mode is enabled."""

    return os.environ.get(LOCAL_NO_LOGIN_ENABLED_ENV, "false").strip().casefold() == "true"


def validate_security_configuration(database_url: str | None = None) -> DeploymentClass:
    deployment = _deployment_class()
    if (
        os.environ.get(SOURCE_RECIPES_LOCAL_ENABLED_ENV, "false").strip().casefold() == "true"
        and deployment != "LOCALHOST_SERVICE"
    ):
        raise SecurityConfigurationError("source_recipes_non_local_forbidden")
    if local_no_login_enabled() and deployment != "LOCALHOST_SERVICE":
        raise SecurityConfigurationError("local_no_login_forbidden")
    if local_no_login_enabled() and auth_enabled():
        raise SecurityConfigurationError("local_no_login_auth_conflict")
    if deployment == "LOCALHOST_SERVICE":
        return deployment
    if not auth_enabled():
        raise SecurityConfigurationError("deployment_auth_required")
    try:
        operator_bootstrap()
    except ValueError as error:
        raise SecurityConfigurationError("auth_secret_missing") from error
    if not cookie_secure():
        raise SecurityConfigurationError("secure_cookie_required")
    if "*" in allowed_origins():
        raise SecurityConfigurationError("wildcard_origin_forbidden")
    if os.environ.get(SECRET_SOURCE_ENV, "environment").strip().casefold() != "managed":
        raise SecurityConfigurationError("managed_secret_source_required")
    configured_database_url = database_url or os.environ.get("DEVRADAR_DATABASE_URL", "")
    if LOCAL_DATABASE_MARKER in configured_database_url:
        raise SecurityConfigurationError("local_database_secret_forbidden")
    return deployment
