"""Versioned deterministic taxonomy, role classification and bounded summaries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from devradar.catalog.models import JobLevel
from devradar.intelligence.evaluation import (
    EvaluationModel,
    RequirementType,
    SkillExpectation,
    canonicalize_skill_name,
)
from devradar.intelligence.models import ExtractionValidationStatus

TAXONOMY_VERSION = "job-taxonomy-v1"
ROLE_SCHEMA_VERSION = "job-role-classification-v1"
SUMMARY_SCHEMA_VERSION = "job-bounded-summary-v1"
MAX_SUMMARY_LENGTH = 420
MAX_SUMMARY_EVIDENCE = 8


class SkillCategory(StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    CLOUD = "cloud"
    DEVOPS = "devops"
    MESSAGING = "messaging"
    TESTING = "testing"
    AI = "ai"
    TOOL = "tool"
    OTHER = "other"


class RoleFamily(StrEnum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    MOBILE = "mobile"
    DATA = "data"
    DEVOPS = "devops"
    QA = "qa"
    SECURITY = "security"
    PRODUCT = "product"
    DESIGN = "design"


class EvidenceKind(StrEnum):
    ROLE = "role"
    LEVEL = "level"
    SKILL = "skill"


class TaxonomySkill(EvaluationModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9.+#-]{0,49}$")
    category: SkillCategory
    requirement_type: RequirementType
    evidence: str = Field(min_length=1, max_length=200)
    confidence: Decimal = Field(ge=0, le=1)
    taxonomy_version: str = Field(default=TAXONOMY_VERSION, min_length=1, max_length=64)


class EvidenceClaim(EvaluationModel):
    kind: EvidenceKind
    text: str = Field(min_length=1, max_length=200)


class RoleClassification(EvaluationModel):
    role: RoleFamily
    levels: tuple[JobLevel, ...] = Field(max_length=7)
    evidence: tuple[EvidenceClaim, ...] = Field(min_length=1, max_length=4)
    confidence: Decimal = Field(ge=0, le=1)
    taxonomy_version: str = Field(default=TAXONOMY_VERSION, min_length=1, max_length=64)
    schema_version: str = Field(default=ROLE_SCHEMA_VERSION, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_evidence_kinds(self) -> RoleClassification:
        kinds = {claim.kind for claim in self.evidence}
        if EvidenceKind.ROLE not in kinds:
            raise ValueError("role classification requires role evidence")
        return self


class BoundedSummary(EvaluationModel):
    text: str = Field(min_length=1, max_length=MAX_SUMMARY_LENGTH)
    evidence: tuple[EvidenceClaim, ...] = Field(
        min_length=1,
        max_length=MAX_SUMMARY_EVIDENCE,
    )
    taxonomy_version: str = Field(default=TAXONOMY_VERSION, min_length=1, max_length=64)
    schema_version: str = Field(default=SUMMARY_SCHEMA_VERSION, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_bounded_text(self) -> BoundedSummary:
        if any(ord(character) < 32 and character not in "\t" for character in self.text):
            raise ValueError("summary text contains a control character")
        if "\n" in self.text or "\r" in self.text:
            raise ValueError("summary text must be a single line")
        evidence_keys = [(claim.kind, claim.text.casefold()) for claim in self.evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("summary evidence must be unique")
        return self


@dataclass(frozen=True, slots=True)
class TaxonomyOutcome:
    status: ExtractionValidationStatus
    skills: tuple[TaxonomySkill, ...]
    errors: list[dict[str, str]] | None = None


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    status: ExtractionValidationStatus
    classification: RoleClassification | None
    errors: list[dict[str, str]] | None = None


@dataclass(frozen=True, slots=True)
class SummaryOutcome:
    status: ExtractionValidationStatus
    summary: BoundedSummary | None
    errors: list[dict[str, str]] | None = None


class TaxonomyValidationError(ValueError):
    """Raised when an untrusted taxonomy/summary candidate is not safe to apply."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_SKILL_CATEGORIES: dict[str, SkillCategory] = {
    "apache-kafka": SkillCategory.MESSAGING,
    "apache-spark": SkillCategory.AI,
    "aws": SkillCategory.CLOUD,
    "c#": SkillCategory.LANGUAGE,
    "dart": SkillCategory.LANGUAGE,
    "docker": SkillCategory.DEVOPS,
    "dotnet": SkillCategory.FRAMEWORK,
    "fastapi": SkillCategory.FRAMEWORK,
    "firebase": SkillCategory.CLOUD,
    "flutter": SkillCategory.FRAMEWORK,
    "go": SkillCategory.LANGUAGE,
    "java": SkillCategory.LANGUAGE,
    "kubernetes": SkillCategory.DEVOPS,
    "next.js": SkillCategory.FRAMEWORK,
    "node.js": SkillCategory.FRAMEWORK,
    "postgresql": SkillCategory.DATABASE,
    "python": SkillCategory.LANGUAGE,
    "react": SkillCategory.FRAMEWORK,
    "redis": SkillCategory.DATABASE,
    "selenium": SkillCategory.TESTING,
    "sql": SkillCategory.DATABASE,
    "terraform": SkillCategory.DEVOPS,
    "typescript": SkillCategory.LANGUAGE,
}


_ROLE_MARKERS: dict[RoleFamily, tuple[str, ...]] = {
    RoleFamily.BACKEND: ("backend", "back-end", "server-side"),
    RoleFamily.FRONTEND: ("frontend", "front-end", "ui engineer"),
    RoleFamily.MOBILE: ("mobile", "android", "ios", "flutter", "react native"),
    RoleFamily.DATA: (
        "data engineer",
        "data scientist",
        "data analyst",
        "machine learning",
        "ml engineer",
    ),
    RoleFamily.DEVOPS: ("devops", "sre", "site reliability", "platform engineer"),
    RoleFamily.QA: ("qa engineer", "quality assurance", "test engineer", "automation test"),
    RoleFamily.SECURITY: (
        "security engineer",
        "cybersecurity",
        "penetration test",
        "application security",
    ),
    RoleFamily.PRODUCT: ("product manager", "product owner"),
    RoleFamily.DESIGN: ("ui/ux", "ux designer", "product designer"),
}
_ROLE_PATTERNS = {
    role: tuple(
        re.compile(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", re.IGNORECASE)
        for marker in markers
    )
    for role, markers in _ROLE_MARKERS.items()
}


def _error(code: str, path: str, error_type: str) -> dict[str, str]:
    return {"code": code, "path": path, "type": error_type}


def classify_skills(skills: Sequence[SkillExpectation]) -> TaxonomyOutcome:
    """Map existing canonical skill mentions without inventing aliases."""

    mapped: list[TaxonomySkill] = []
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, RequirementType]] = set()
    for index, skill in enumerate(skills):
        name = canonicalize_skill_name(skill.name)
        key = (name, skill.requirement_type)
        if key in seen:
            errors.append(_error("skill_duplicate", f"skills[{index}]", "invalid"))
            continue
        seen.add(key)
        category = _SKILL_CATEGORIES.get(name, SkillCategory.OTHER)
        mapped.append(
            TaxonomySkill(
                name=name,
                category=category,
                requirement_type=skill.requirement_type,
                evidence=skill.evidence,
                confidence=Decimal("1") if category is not SkillCategory.OTHER else Decimal("0.5"),
            )
        )
        if category is SkillCategory.OTHER:
            errors.append(_error("skill_taxonomy_unknown", f"skills[{index}]", "review"))
    status = (
        ExtractionValidationStatus.REJECTED
        if any(error["type"] == "invalid" for error in errors)
        else ExtractionValidationStatus.NEEDS_REVIEW
        if errors
        else ExtractionValidationStatus.ACCEPTED
    )
    return TaxonomyOutcome(status=status, skills=tuple(mapped), errors=errors or None)


def _role_matches(text: str, *, title: bool) -> dict[RoleFamily, tuple[int, str]]:
    matches: dict[RoleFamily, tuple[int, str]] = {}
    for role, patterns in _ROLE_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match is not None:
                matches[role] = (3 if title else 1, match.group(0))
                break
    return matches


def classify_role(
    title: str,
    description_text: str,
    *,
    levels: tuple[JobLevel, ...],
    level_evidence: str | None = None,
) -> ClassificationOutcome:
    """Classify a role only when a deterministic marker has a unique winner."""

    title_matches = _role_matches(title, title=True)
    description_matches = _role_matches(description_text, title=False)
    scores: dict[RoleFamily, int] = {}
    evidence: dict[RoleFamily, list[EvidenceClaim]] = {}
    for role, (score, marker) in title_matches.items():
        scores[role] = scores.get(role, 0) + score
        evidence.setdefault(role, []).append(EvidenceClaim(kind=EvidenceKind.ROLE, text=marker))
    for role, (score, marker) in description_matches.items():
        scores[role] = scores.get(role, 0) + score
        if role not in title_matches:
            evidence.setdefault(role, []).append(EvidenceClaim(kind=EvidenceKind.ROLE, text=marker))
    if not scores:
        return ClassificationOutcome(
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            classification=None,
            errors=[_error("role_not_determined", "role", "review")],
        )
    highest = max(scores.values())
    winners = tuple(role for role, score in scores.items() if score == highest)
    if len(winners) != 1:
        return ClassificationOutcome(
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            classification=None,
            errors=[_error("role_ambiguous", "role", "review")],
        )
    winner = winners[0]
    claims = evidence[winner]
    if level_evidence and level_evidence.strip():
        claims.append(EvidenceClaim(kind=EvidenceKind.LEVEL, text=level_evidence.strip()))
    confidence = Decimal("0.9") if winner in title_matches else Decimal("0.7")
    classification = RoleClassification(
        role=winner,
        levels=levels,
        evidence=tuple(claims),
        confidence=confidence,
    )
    return ClassificationOutcome(
        status=ExtractionValidationStatus.ACCEPTED,
        classification=classification,
    )


def _source_contains_claims(summary: BoundedSummary, source_text: str) -> bool:
    return all(claim.text.casefold() in source_text.casefold() for claim in summary.evidence)


def _render_summary_text(
    role: RoleFamily,
    role_claim: EvidenceClaim,
    skill_claims: Sequence[EvidenceClaim],
) -> str:
    text = f"Role: {role.value} ({role_claim.text})."
    if skill_claims:
        text += " Skills: " + ", ".join(claim.text for claim in skill_claims) + "."
    return text


def _role_from_evidence(claims: Sequence[EvidenceClaim]) -> RoleFamily | None:
    matched: set[RoleFamily] = set()
    for claim in claims:
        if claim.kind is not EvidenceKind.ROLE:
            continue
        for role, patterns in _ROLE_PATTERNS.items():
            if any(pattern.search(claim.text) for pattern in patterns):
                matched.add(role)
    return next(iter(matched)) if len(matched) == 1 else None


def build_bounded_summary(
    *,
    classification: ClassificationOutcome,
    skills: TaxonomyOutcome,
    source_text: str,
) -> SummaryOutcome:
    """Render a short summary from accepted evidence only."""

    if classification.status is not ExtractionValidationStatus.ACCEPTED:
        return SummaryOutcome(
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            summary=None,
            errors=[_error("classification_not_accepted", "classification", "review")],
        )
    if skills.status is not ExtractionValidationStatus.ACCEPTED:
        return SummaryOutcome(
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            summary=None,
            errors=[_error("taxonomy_not_accepted", "skills", "review")],
        )
    if classification.classification is None:
        return SummaryOutcome(
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            summary=None,
            errors=[_error("classification_not_accepted", "classification", "review")],
        )
    claims = list(classification.classification.evidence)
    claims.extend(
        EvidenceClaim(kind=EvidenceKind.SKILL, text=skill.evidence) for skill in skills.skills
    )
    claims = claims[:MAX_SUMMARY_EVIDENCE]
    if not claims or any(claim.text.casefold() not in source_text.casefold() for claim in claims):
        return SummaryOutcome(
            status=ExtractionValidationStatus.REJECTED,
            summary=None,
            errors=[_error("summary_evidence_invalid", "evidence", "invalid")],
        )
    role_claim = next(claim for claim in claims if claim.kind is EvidenceKind.ROLE)
    skill_claims = [claim for claim in claims if claim.kind is EvidenceKind.SKILL]
    text = _render_summary_text(classification.classification.role, role_claim, skill_claims)
    try:
        summary = BoundedSummary(evidence=tuple(claims), text=text)
    except ValueError:
        return SummaryOutcome(
            status=ExtractionValidationStatus.REJECTED,
            summary=None,
            errors=[_error("summary_schema_invalid", "summary", "invalid")],
        )
    return SummaryOutcome(status=ExtractionValidationStatus.ACCEPTED, summary=summary)


def validate_summary_candidate(
    candidate: Mapping[str, object],
    *,
    source_text: str,
) -> BoundedSummary:
    """Validate untrusted summary output without accepting unsupported domain claims."""

    try:
        summary = BoundedSummary.model_validate(candidate)
    except ValueError:
        raise TaxonomyValidationError("summary_schema_invalid") from None
    if summary.taxonomy_version != TAXONOMY_VERSION:
        raise TaxonomyValidationError("summary_taxonomy_version_invalid")
    if summary.schema_version != SUMMARY_SCHEMA_VERSION:
        raise TaxonomyValidationError("summary_schema_version_invalid")
    if not _source_contains_claims(summary, source_text):
        raise TaxonomyValidationError("summary_evidence_invalid")
    role = _role_from_evidence(summary.evidence)
    if role is None:
        raise TaxonomyValidationError("summary_unsupported_claim")
    role_claim = next(claim for claim in summary.evidence if claim.kind is EvidenceKind.ROLE)
    skill_claims = [claim for claim in summary.evidence if claim.kind is EvidenceKind.SKILL]
    if summary.text != _render_summary_text(role, role_claim, skill_claims):
        raise TaxonomyValidationError("summary_unsupported_claim")
    return summary
