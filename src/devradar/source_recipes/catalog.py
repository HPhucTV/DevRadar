"""Versioned notice-only catalog for known job listing origins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from devradar.source_recipes.models import SourceRecipeError, TermsNotice
from devradar.source_recipes.policy import normalize_listing_url

CATALOG_SCHEMA_VERSION = "source-catalog-v1"
_REVIEW_DATE = date(2026, 8, 24)


@dataclass(frozen=True, slots=True)
class SourceCatalogEntry:
    name: str
    origin: str
    listing_hint: str
    notice: TermsNotice
    evidence_url: str
    reviewed_on: date


@dataclass(frozen=True, slots=True)
class ResolvedTermsNotice:
    origin: str
    notice: TermsNotice
    version: str
    evidence_url: str | None
    reviewed_on: date | None
    acknowledgement_required: bool


SOURCE_CATALOG = (
    SourceCatalogEntry(
        "ITviec",
        "https://itviec.com",
        "/it-jobs",
        TermsNotice.RESTRICTED_TERMS,
        "https://itviec.com/blog/terms-and-conditions/",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "TopDev",
        "https://topdev.vn",
        "/viec-lam-it",
        TermsNotice.NO_SPECIFIC_RESTRICTION_FOUND,
        "https://topdev.vn/term-of-services",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "VietnamWorks",
        "https://www.vietnamworks.com",
        "/viec-lam",
        TermsNotice.NOT_REVIEWED,
        "https://www.vietnamworks.com/robots.txt",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "TopCV",
        "https://www.topcv.vn",
        "/viec-lam",
        TermsNotice.RESTRICTED_TERMS,
        "https://www.topcv.vn/terms-of-service",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "Glints",
        "https://glints.com",
        "/vn/opportunities/jobs/explore",
        TermsNotice.RESTRICTED_TERMS,
        "https://glints.com/vn/about/terms",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "CareerViet",
        "https://careerviet.vn",
        "/viec-lam/tat-ca-viec-lam-vi.html",
        TermsNotice.RESTRICTED_TERMS,
        "https://careerviet.vn/vi/jobseekers/use",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "JobsGO",
        "https://jobsgo.vn",
        "/viec-lam.html",
        TermsNotice.RESTRICTED_TERMS,
        "https://jobsgo.vn/site/term-of-service",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "Indeed Vietnam",
        "https://vn.indeed.com",
        "/jobs",
        TermsNotice.RESTRICTED_TERMS,
        "https://www.indeed.com/legal",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "CareerLink",
        "https://www.careerlink.vn",
        "/vieclam/list",
        TermsNotice.RESTRICTED_TERMS,
        "https://www.careerlink.vn/thoa-thuan-su-dung",
        _REVIEW_DATE,
    ),
    SourceCatalogEntry(
        "Vieclam24h",
        "https://vieclam24h.vn",
        "/viec-lam-toan-quoc-p136.html",
        TermsNotice.NO_SPECIFIC_RESTRICTION_FOUND,
        "https://vieclam24h.vn/dieu-khoan-su-dung.html",
        _REVIEW_DATE,
    ),
)

_CATALOG_BY_ORIGIN = {entry.origin: entry for entry in SOURCE_CATALOG}


def _notice_version(
    *,
    origin: str,
    notice: TermsNotice,
    evidence_url: str | None,
    reviewed_on: date | None,
) -> str:
    payload = "|".join(
        (
            CATALOG_SCHEMA_VERSION,
            origin,
            notice.value,
            evidence_url or "",
            reviewed_on.isoformat() if reviewed_on is not None else "",
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def resolve_terms_notice(listing_url: str) -> ResolvedTermsNotice:
    origin = normalize_listing_url(listing_url).origin
    entry = _CATALOG_BY_ORIGIN.get(origin)
    notice = entry.notice if entry is not None else TermsNotice.NOT_REVIEWED
    evidence_url = entry.evidence_url if entry is not None else None
    reviewed_on = entry.reviewed_on if entry is not None else None
    return ResolvedTermsNotice(
        origin=origin,
        notice=notice,
        version=_notice_version(
            origin=origin,
            notice=notice,
            evidence_url=evidence_url,
            reviewed_on=reviewed_on,
        ),
        evidence_url=evidence_url,
        reviewed_on=reviewed_on,
        acknowledgement_required=notice in {TermsNotice.NOT_REVIEWED, TermsNotice.RESTRICTED_TERMS},
    )


def validate_notice_acknowledgement(
    notice: ResolvedTermsNotice,
    *,
    acknowledged_version: str | None,
) -> None:
    if not notice.acknowledgement_required:
        return
    if acknowledged_version is None:
        raise SourceRecipeError("terms_notice_acknowledgement_required")
    if acknowledged_version != notice.version:
        raise SourceRecipeError("terms_notice_acknowledgement_stale")
