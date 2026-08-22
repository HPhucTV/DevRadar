"""FastAPI dependencies for session authentication and owner/operator policy."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.api.errors import ApiContractError
from devradar.auth.models import AuthRole, AuthSession, User
from devradar.auth.service import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    allowed_origins,
    auth_enabled,
    hash_token,
    is_expired,
    owner_hash_for_subject,
)
from devradar.platform.database import _database_engine, get_database_session, get_database_url

DatabaseSession = Annotated[Session, Depends(get_database_session)]
_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{31,127}$")


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    auth_session: AuthSession


def _unauthorized() -> ApiContractError:
    return ApiContractError(
        status.HTTP_401_UNAUTHORIZED,
        "auth_required",
        "Authentication is required for this resource.",
    )


def _load_context(session: Session, token: str | None) -> AuthContext:
    if not token:
        raise _unauthorized()
    row = session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == hash_token(token))
    ).first()
    if row is None:
        raise _unauthorized()
    auth_session, user = row
    now = datetime.now(UTC)
    if auth_session.revoked_at is not None or is_expired(auth_session.expires_at, now=now):
        raise _unauthorized()
    if not user.is_active:
        raise _unauthorized()
    return AuthContext(user=user, auth_session=auth_session)


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if origin and origin not in allowed_origins():
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "csrf_origin_invalid",
            "The request origin is not allowed.",
        )


def validate_csrf(request: Request, context: AuthContext) -> None:
    """Validate the double-submit CSRF cookie/header pair for a mutation."""

    _validate_origin(request)
    header_token = request.headers.get(CSRF_HEADER, "")
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if (
        not header_token
        or not cookie_token
        or not hmac.compare_digest(header_token, cookie_token)
        or not hmac.compare_digest(hash_token(header_token), context.auth_session.csrf_hash)
    ):
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "csrf_invalid",
            "A valid CSRF token is required.",
        )


def require_authenticated_user(
    request: Request,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthContext:
    del request
    if not auth_enabled():
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "auth_disabled",
            "Authentication is disabled for this deployment.",
        )
    return _load_context(session, session_token)


def require_csrf(
    request: Request,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthContext:
    context = require_authenticated_user(request, session, session_token)
    validate_csrf(request, context)
    return context


def _load_context_from_database(token: str | None) -> AuthContext:
    with Session(_database_engine(get_database_url())) as session:
        return _load_context(session, token)


def require_owner_hash(
    request: Request,
    owner_token: Annotated[
        str | None, Header(alias="X-DevRadar-Owner", include_in_schema=False)
    ] = None,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> str:
    """Return the stable owner scope, using sessions when auth is enabled."""

    if auth_enabled():
        if owner_token is not None:
            raise ApiContractError(
                status.HTTP_403_FORBIDDEN,
                "legacy_owner_header_rejected",
                "The legacy owner header is not accepted when authentication is enabled.",
            )
        context = _load_context_from_database(session_token)
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            validate_csrf(request, context)
        return owner_hash_for_subject(context.user.id)

    if owner_token is None or _OWNER_PATTERN.fullmatch(owner_token) is None:
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "resume_owner_invalid",
            "A valid local owner token is required.",
        )
    return hash_token(owner_token)


def require_operator(
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthContext | None:
    """Require operator role in auth mode; preserve local compatibility otherwise."""

    if not auth_enabled():
        return None
    context = _load_context_from_database(session_token)
    if context.user.role != AuthRole.OPERATOR.value:
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "operator_required",
            "Operator role is required for this resource.",
        )
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        validate_csrf(request, context)
    return context
