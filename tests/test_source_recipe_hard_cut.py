from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOVED_TOKENS = (
    "vng_careers",
    "momo_careers",
    "greenhouse_job_board",
    "remotejobs_api",
    "CustomSourceAdapter",
    "/api/v1/custom-sources",
    "custom-source-worker",
    "DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED",
    "customSources",
    "custom-source-",
    "custom_sources",
)
REMOVED_PATHS = (
    "src/devradar/custom_sources",
    "src/devradar/api/custom_sources.py",
    "src/devradar/ingestion/adapters/custom.py",
    "src/devradar/ingestion/adapters/greenhouse.py",
    "src/devradar/ingestion/adapters/momo.py",
    "src/devradar/ingestion/adapters/remotejobs.py",
    "src/devradar/ingestion/adapters/vng.py",
    "web/src/components/custom-source-panel.tsx",
    "web/src/lib/custom-sources.ts",
    "web/src/app/api/devradar/custom-sources",
)


def _active_files() -> list[Path]:
    files = [ROOT / "compose.yaml"]
    for base in (ROOT / "src", ROOT / "web" / "src", ROOT / "tests"):
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".ts", ".tsx", ".json", ".yaml"}
            and path.name != Path(__file__).name
        )
    return files


def test_legacy_source_runtime_is_absent() -> None:
    active = "\n".join(path.read_text(encoding="utf-8") for path in _active_files())

    for token in REMOVED_TOKENS:
        assert token not in active
    for relative in REMOVED_PATHS:
        path = ROOT / relative
        if path.suffix:
            assert not path.exists()
        else:
            assert not any(
                candidate.is_file() and candidate.suffix in {".py", ".ts", ".tsx"}
                for candidate in path.rglob("*")
            )
