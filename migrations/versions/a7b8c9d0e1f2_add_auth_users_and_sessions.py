"""Add PostgreSQL-backed authentication identities and sessions.

Revision ID: a7b8c9d0e1f2
Revises: f2a4b6c8d0e1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7b8c9d0e1f2"
down_revision = "f2a4b6c8d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default=sa.text("'owner'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
            name="ck_auth_users_username",
        ),
        sa.CheckConstraint("role IN ('owner', 'operator')", name="ck_auth_users_role"),
        sa.CheckConstraint("length(password_hash) BETWEEN 32 AND 255", name="ck_auth_users_hash"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_auth_users_username", "auth_users", ["username"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_auth_sessions_token_hash"),
        sa.CheckConstraint("length(csrf_hash) = 64", name="ck_auth_sessions_csrf_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["auth_users.id"], ondelete="CASCADE", name="fk_auth_sessions_user"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_expiry", table_name="auth_sessions")
    op.drop_index("uq_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("uq_auth_users_username", table_name="auth_users")
    op.drop_table("auth_users")
