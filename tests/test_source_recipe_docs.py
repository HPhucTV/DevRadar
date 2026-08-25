from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    name: (ROOT / path).read_text(encoding="utf-8")
    for name, path in {
        "readme": "README.md",
        "agents": "AGENTS.md",
        "product": "docs/PRODUCT.md",
        "architecture": "docs/ARCHITECTURE.md",
        "domain": "docs/DOMAIN_MODEL.md",
        "ingestion": "docs/INGESTION.md",
        "api": "docs/API.md",
        "operations": "docs/OPERATIONS.md",
        "roadmap": "docs/ROADMAP.md",
        "decisions": "docs/decisions/README.md",
    }.items()
}


def test_readme_documents_one_click_local_recipe_workflow_without_stale_metrics() -> None:
    readme = DOCS["readme"]
    operations = DOCS["operations"]

    assert "start-devradar.cmd" in readme
    assert "http://127.0.0.1:3000/sources" in readme
    assert "Source Recipe" in readme
    assert "tự mở Docker Desktop" in readme
    assert "180 giây" in readme
    assert "không tự cài" in readme
    assert "`desktop-linux`" in readme
    assert "Docker Desktop" in operations
    assert "180 giây" in operations
    assert "mở thủ công" in operations
    assert "Docker context từ xa" in operations
    assert "probe bị treo" in operations
    for stale in ("3,339", "1,003", "0.9583"):
        assert stale not in readme


def test_active_contracts_describe_the_recipe_boundary_consistently() -> None:
    assert "terms_notice" in DOCS["product"]
    assert "owner acknowledgement" in DOCS["product"].casefold()
    assert "SourceRecipe" in DOCS["architecture"]
    assert "SourceRecipePreview" in DOCS["domain"]
    ingestion = DOCS["ingestion"]
    for term in (
        "structured data",
        "Playwright",
        "visual mapping",
        "mapping_required",
        "layout_unavailable",
        "source_unavailable",
        "every_6_hours",
        "incomplete",
        "CAPTCHA",
    ):
        assert term in ingestion
    assert "không bypass" in ingestion.casefold()
    assert "pending|running|succeeded|failed" in DOCS["domain"]
    assert "mapping_required" in DOCS["api"]
    assert "source_unavailable" in DOCS["api"]
    for term in (
        "proposedHosts",
        "proposedPathPrefixes",
        "preview_hosts_confirmation_required",
        "preview_hosts_confirmation_invalid",
    ):
        assert term in DOCS["api"]
    assert "canonical job URL" in ingestion
    assert "browser subresource" in ingestion
    assert "preview_hosts_confirmation_required" in DOCS["domain"]


def test_api_and_operator_docs_publish_only_current_recipe_commands() -> None:
    api = DOCS["api"]
    for route in (
        "GET /api/v1/source-catalog",
        "POST /api/v1/source-recipes",
        "POST /api/v1/source-recipes/{recipeId}/previews",
        "POST /api/v1/source-recipes/{recipeId}/previews/{previewId}/mapping",
        "GET/POST /api/v1/source-recipes/{recipeId}/crawl-runs",
    ):
        assert route in api

    current = "\n".join(
        DOCS[name]
        for name in (
            "readme",
            "agents",
            "product",
            "architecture",
            "domain",
            "ingestion",
            "api",
            "operations",
        )
    )
    for removed in (
        "custom" + "-source-worker",
        "DEVRADAR_CUSTOM" + "_SOURCES_LOCAL_ENABLED",
        "/api/v1/custom" + "-sources",
        "crawl --source",
        "adapters/greenhouse.py",
        "adapters/vng.py",
        "adapters/momo.py",
    ):
        assert removed not in current
    assert "source-recipe-worker" in DOCS["agents"]
    assert "start-devradar.cmd" in DOCS["operations"]


def test_current_decision_and_roadmap_preserve_history_without_active_claims() -> None:
    decisions = DOCS["decisions"]
    roadmap = DOCS["roadmap"]

    assert "ADR-026" in decisions and "Accepted" in decisions
    assert "ADR-024" in decisions and "Superseded" in decisions
    assert "V6-016 historical" in roadmap
    assert "V6-020" in roadmap
    assert "V6-020-no-code-source-recipes.md" in roadmap


def test_active_documentation_local_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    paths = (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        *(
            ROOT / name
            for name in (
                "docs/PRODUCT.md",
                "docs/ARCHITECTURE.md",
                "docs/DOMAIN_MODEL.md",
                "docs/INGESTION.md",
                "docs/API.md",
                "docs/AI.md",
                "docs/OPERATIONS.md",
                "docs/ROADMAP.md",
                "docs/decisions/README.md",
            )
        ),
    )

    missing: list[str] = []
    for document in paths:
        for target in link_pattern.findall(document.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            relative = target.split("#", maxsplit=1)[0]
            if relative and not (document.parent / relative).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {relative}")

    assert missing == []
