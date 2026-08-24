"""Shared visibility predicate for approved and explicit localhost recipe sources."""

from __future__ import annotations

from sqlalchemy import ColumnElement

from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.platform.security_config import source_recipes_local_enabled


def visible_source_condition() -> ColumnElement[bool]:
    statuses = [SourceApprovalStatus.APPROVED]
    if source_recipes_local_enabled():
        statuses.append(SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL)
    return Source.approval_status.in_(statuses)
