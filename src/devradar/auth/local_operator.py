"""Idempotent PostgreSQL identity for explicit localhost no-login mode."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.auth.models import AuthRole, User

LOCAL_OPERATOR_USERNAME = "local-operator"
LOCAL_OPERATOR_PASSWORD_DISABLED = (
    "local-no-login-disabled$0000000000000000000000000000000000000000"
)


class LocalOperatorUnavailable(RuntimeError):
    """Raised when the reserved local identity cannot be used safely."""


def get_or_create_local_operator(session: Session) -> User:
    """Return the reserved operator without creating a password or session."""

    user = session.scalar(select(User).where(User.username == LOCAL_OPERATOR_USERNAME))
    if user is None:
        now = datetime.now(UTC)
        user = User(
            username=LOCAL_OPERATOR_USERNAME,
            password_hash=LOCAL_OPERATOR_PASSWORD_DISABLED,
            role=AuthRole.OPERATOR.value,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            user = session.scalar(select(User).where(User.username == LOCAL_OPERATOR_USERNAME))
            if user is None:
                raise

    if (
        not user.is_active
        or user.role != AuthRole.OPERATOR.value
        or user.password_hash != LOCAL_OPERATOR_PASSWORD_DISABLED
    ):
        raise LocalOperatorUnavailable("local_operator_invalid")
    return user
