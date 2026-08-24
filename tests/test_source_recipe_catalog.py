from __future__ import annotations

import importlib

import pytest

from devradar.source_recipes.models import TermsNotice


def _catalog_module() -> object:
    return importlib.import_module("devradar.source_recipes.catalog")


def test_catalog_has_exact_ten_notice_only_shortcuts() -> None:
    catalog = _catalog_module()
    entries = catalog.SOURCE_CATALOG  # type: ignore[attr-defined]
    assert len(entries) == 10
    assert {entry.origin: entry.notice for entry in entries} == {
        "https://itviec.com": TermsNotice.RESTRICTED_TERMS,
        "https://topdev.vn": TermsNotice.NO_SPECIFIC_RESTRICTION_FOUND,
        "https://www.vietnamworks.com": TermsNotice.NOT_REVIEWED,
        "https://www.topcv.vn": TermsNotice.RESTRICTED_TERMS,
        "https://glints.com": TermsNotice.RESTRICTED_TERMS,
        "https://careerviet.vn": TermsNotice.RESTRICTED_TERMS,
        "https://jobsgo.vn": TermsNotice.RESTRICTED_TERMS,
        "https://vn.indeed.com": TermsNotice.RESTRICTED_TERMS,
        "https://www.careerlink.vn": TermsNotice.RESTRICTED_TERMS,
        "https://vieclam24h.vn": TermsNotice.NO_SPECIFIC_RESTRICTION_FOUND,
    }
    assert all(entry.listing_hint.startswith("/") for entry in entries)
    assert all(entry.evidence_url.startswith("https://") for entry in entries)
    assert all(entry.reviewed_on.isoformat() == "2026-08-24" for entry in entries)
    assert not any(hasattr(entry, "adapter") for entry in entries)


def test_restricted_notice_requires_exact_version_acknowledgement() -> None:
    catalog = _catalog_module()
    notice = catalog.resolve_terms_notice(  # type: ignore[attr-defined]
        "https://www.topcv.vn/viec-lam"
    )
    assert notice.notice is TermsNotice.RESTRICTED_TERMS
    assert notice.acknowledgement_required is True
    assert len(notice.version) == 64

    with pytest.raises(ValueError, match="terms_notice_acknowledgement_required"):
        catalog.validate_notice_acknowledgement(  # type: ignore[attr-defined]
            notice, acknowledged_version=None
        )
    with pytest.raises(ValueError, match="terms_notice_acknowledgement_stale"):
        catalog.validate_notice_acknowledgement(  # type: ignore[attr-defined]
            notice, acknowledged_version="0" * 64
        )
    catalog.validate_notice_acknowledgement(  # type: ignore[attr-defined]
        notice, acknowledged_version=notice.version
    )


def test_unknown_origin_is_versioned_not_reviewed_notice() -> None:
    catalog = _catalog_module()
    first = catalog.resolve_terms_notice("https://jobs.example.test/list")  # type: ignore[attr-defined]
    second = catalog.resolve_terms_notice("https://other.example.test/list")  # type: ignore[attr-defined]

    assert first.notice is TermsNotice.NOT_REVIEWED
    assert first.acknowledgement_required is True
    assert first.evidence_url is None
    assert first.reviewed_on is None
    assert first.version != second.version


def test_notice_without_specific_restriction_does_not_require_acknowledgement() -> None:
    catalog = _catalog_module()
    notice = catalog.resolve_terms_notice("https://topdev.vn/viec-lam-it")  # type: ignore[attr-defined]
    assert notice.notice is TermsNotice.NO_SPECIFIC_RESTRICTION_FOUND
    assert notice.acknowledgement_required is False
    catalog.validate_notice_acknowledgement(notice, acknowledged_version=None)  # type: ignore[attr-defined]
