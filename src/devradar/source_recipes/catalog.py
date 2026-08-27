"""Versioned URL shortcuts for known job listing origins."""

from __future__ import annotations

from dataclasses import dataclass

CATALOG_SCHEMA_VERSION = "source-catalog-v2"


@dataclass(frozen=True, slots=True)
class SourceCatalogEntry:
    name: str
    origin: str
    listing_hint: str


SOURCE_CATALOG = (
    SourceCatalogEntry(
        "ITviec",
        "https://itviec.com",
        "/it-jobs",
    ),
    SourceCatalogEntry(
        "TopDev",
        "https://topdev.vn",
        "/viec-lam-it",
    ),
    SourceCatalogEntry(
        "VietnamWorks",
        "https://www.vietnamworks.com",
        "/viec-lam",
    ),
    SourceCatalogEntry(
        "TopCV",
        "https://www.topcv.vn",
        "/viec-lam",
    ),
    SourceCatalogEntry(
        "Glints",
        "https://glints.com",
        "/vn/opportunities/jobs/explore",
    ),
    SourceCatalogEntry(
        "CareerViet",
        "https://careerviet.vn",
        "/viec-lam/tat-ca-viec-lam-vi.html",
    ),
    SourceCatalogEntry(
        "JobsGO",
        "https://jobsgo.vn",
        "/viec-lam.html",
    ),
    SourceCatalogEntry(
        "Indeed Vietnam",
        "https://vn.indeed.com",
        "/jobs",
    ),
    SourceCatalogEntry(
        "CareerLink",
        "https://www.careerlink.vn",
        "/vieclam/list",
    ),
    SourceCatalogEntry(
        "Vieclam24h",
        "https://vieclam24h.vn",
        "/viec-lam-toan-quoc-p136.html",
    ),
)
