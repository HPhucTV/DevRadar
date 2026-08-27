from __future__ import annotations

import dataclasses
import importlib


def _catalog_module() -> object:
    return importlib.import_module("devradar.source_recipes.catalog")


def test_catalog_is_exact_ten_bounded_url_shortcuts_v2() -> None:
    catalog = _catalog_module()
    entries = catalog.SOURCE_CATALOG  # type: ignore[attr-defined]

    assert catalog.CATALOG_SCHEMA_VERSION == "source-catalog-v2"  # type: ignore[attr-defined]
    assert {
        field.name
        for field in dataclasses.fields(catalog.SourceCatalogEntry)  # type: ignore[attr-defined]
    } == {"name", "origin", "listing_hint"}
    assert len(entries) == 10
    assert all(entry.listing_hint.startswith("/") for entry in entries)
    assert not any(hasattr(entry, "adapter") for entry in entries)
