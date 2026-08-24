"""Opt-in session login/logout/me endpoints for V6 authentication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.api.common import ApiModel, DataResponse, ErrorResponse
from devradar.api.errors import ApiContractError
from devradar.auth.dependencies import (
    AuthContext,
    DatabaseSession,
    require_authenticated_user,
    require_csrf,
)
from devradar.auth.models import AuthRole, AuthSession, User
from devradar.auth.service import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    auth_enabled,
    cookie_secure,
    hash_token,
    new_token,
    operator_bootstrap,
    session_ttl_seconds,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(ApiModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class AuthUserData(ApiModel):
    username: str
    role: AuthRole


class LoginData(ApiModel):
    user: AuthUserData
    csrf_token: str


AuthResponse = DataResponse[LoginData]
MeResponse = DataResponse[AuthUserData]


def _user_data(user: User) -> AuthUserData:
    return AuthUserData(username=user.username, role=AuthRole(user.role))


def _require_enabled() -> None:
    if not auth_enabled():
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "auth_disabled",
            "Authentication is disabled for this deployment.",
        )


def _bootstrap_user(session: Session, username: str, password_hash: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username))
    if user is not None:
        return user
    user = User(
        username=username,
        password_hash=password_hash,
        role=AuthRole.OPERATOR.value,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    return user


def _auth_configuration() -> tuple[str, str, int]:
    try:
        username, password_hash = operator_bootstrap()
        ttl = session_ttl_seconds()
    except ValueError as error:
        raise ApiContractError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "auth_not_configured",
            "Authentication is not configured for this deployment.",
        ) from error
    return username, password_hash, ttl


def _set_auth_cookies(response: Response, *, session_token: str, csrf_token: str, ttl: int) -> None:
    secure = cookie_secure()
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=ttl,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=ttl,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def login(request: LoginRequest, response: Response, session: DatabaseSession) -> AuthResponse:
    _require_enabled()
    bootstrap_username, bootstrap_hash, ttl = _auth_configuration()
    username = request.username.strip().casefold()
    if username == bootstrap_username:
        user = _bootstrap_user(session, bootstrap_username, bootstrap_hash)
    else:
        user = session.scalar(select(User).where(User.username == username))
    password_hash = user.password_hash if user is not None else bootstrap_hash
    password_valid = verify_password(request.password, password_hash)
    if user is None or not user.is_active or not password_valid:
        session.rollback()
        raise ApiContractError(
            status.HTTP_401_UNAUTHORIZED,
            "auth_invalid_credentials",
            "Username or password is invalid.",
        )
    now = datetime.now(UTC)
    session_token = new_token()
    csrf_token = new_token()
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(session_token),
            csrf_hash=hash_token(csrf_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
    )
    session.commit()
    _set_auth_cookies(response, session_token=session_token, csrf_token=csrf_token, ttl=ttl)
    return AuthResponse(data=LoginData(user=_user_data(user), csrf_token=csrf_token))


@router.get(
    "/me",
    response_model=MeResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def me(context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> MeResponse:
    return MeResponse(data=_user_data(context.user))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def logout(
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    session: DatabaseSession,
) -> Response:
    if context.auth_session is None:
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "auth_disabled",
            "Authentication is disabled for this deployment.",
        )
    context.auth_session.revoked_at = datetime.now(UTC)
    session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response
