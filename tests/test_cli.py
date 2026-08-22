from __future__ import annotations

import json
from pathlib import Path

import pytest

import devradar.cli as cli
from devradar.cli import main
from devradar.platform.database import DATABASE_URL_ENV


def test_cli_database_configuration_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    exit_code = main(["crawl", "--source", "vng-careers", "--max-items", "1"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "ingestion_failed",
            "message": "Ingestion could not start or complete safely.",
        }
    }
    assert DATABASE_URL_ENV not in captured.err


def test_cli_rejects_non_registry_source_before_database_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(SystemExit) as captured:
        main(["crawl", "--source", "geocomply-lever"])

    assert captured.value.code == 2


def test_work_one_reports_empty_queue_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_database_url", lambda: "sqlite://")
    monkeypatch.setattr(cli, "work_one_pending_run", lambda session, *, deadline: None)

    exit_code = main(["work-one", "--deadline-minutes", "5"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"processed": False}
    assert captured.err == ""


def test_download_embedding_model_uses_fixed_boundary_without_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    target = tmp_path / "model"
    monkeypatch.setattr(cli, "get_embedding_model_path", lambda: target)
    monkeypatch.setattr(cli, "download_embedding_model", lambda path: path)

    exit_code = main(["download-embedding-model"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {
        "model": "intfloat/multilingual-e5-small",
        "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "ready": True,
    }
    assert captured.err == ""


def test_embed_jobs_rejects_unbounded_batch_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(SystemExit) as captured:
        main(["embed-jobs", "--max-items", "1001"])

    assert captured.value.code == 2


def test_embed_jobs_reports_safe_embedding_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_database_url", lambda: "sqlite://")

    def unavailable(_path: Path) -> None:
        raise RuntimeError("sensitive-model-path")

    monkeypatch.setattr(cli, "LocalEmbeddingModel", unavailable)

    exit_code = main(["embed-jobs", "--max-items", "1"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "embedding_failed",
            "message": "Embedding batch could not start or complete safely.",
        }
    }
    assert "sensitive-model-path" not in captured.err
