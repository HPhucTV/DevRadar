from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_custom_source_docs_share_one_boundary_and_lifecycle() -> None:
    docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "AGENTS.md",
            "docs/DOMAIN_MODEL.md",
            "docs/INGESTION.md",
            "docs/API.md",
            "docs/ARCHITECTURE.md",
        )
    )
    for term in (
        "owner_authorized_local",
        "DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED",
        "permission_required",
        "preview",
        "CrawlRun",
        "RawJobSnapshot",
        "JobChange",
        "missing",
        "removed",
    ):
        assert term in docs
    assert "CAPTCHA" in docs
    assert "anti-bot" in docs
    assert "permission acknowledgement" in docs.lower()


def test_custom_source_docs_link_existing_design_and_adr() -> None:
    for relative in (
        "docs/superpowers/specs/2026-08-23-custom-source-profile-design.md",
        "docs/decisions/0024-accept-local-custom-source-profiles-without-bypass.md",
    ):
        assert (ROOT / relative).is_file()


def test_readme_does_not_describe_closed_v6_016_gates_as_pending() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Custom source profiles đang được triển khai" not in readme
    assert (
        "Full PostgreSQL/browser/Compose evidence cho custom flow vẫn là gate đang chờ"
        not in readme
    )


def test_custom_source_docs_define_transport_safe_path_syntax() -> None:
    api = (ROOT / "docs/API.md").read_text(encoding="utf-8")
    ingestion = (ROOT / "docs/INGESTION.md").read_text(encoding="utf-8")

    for document in (api, ingestion):
        assert "printable ASCII" in document
        assert "encoded slash/backslash" in document
        assert "nested percent" in document
