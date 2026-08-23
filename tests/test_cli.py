from __future__ import annotations

import getpass
import json
from pathlib import Path

import pytest

import devradar.cli as cli
from devradar.auth.service import verify_password
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


def test_custom_source_worker_can_poll_once_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_database_url", lambda: "sqlite://")
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    monkeypatch.setattr(cli, "work_one_custom_source", lambda session, *, deadline: None)

    exit_code = main(["custom-source-worker", "--once"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"lastStatus": None, "processed": 0}
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
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "revision": "faf4aa4225822f3bc6376869cb1164e8e3feedd0",
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


def test_auth_hash_password_reads_secret_from_prompt_and_prints_only_hash(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "local operator password"
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: password)

    exit_code = main(["auth-hash-password"])

    captured = capsys.readouterr()
    encoded = captured.out.strip()
    assert exit_code == 0
    assert verify_password(password, encoded)
    assert password not in captured.out
    assert password not in captured.err


def test_auth_hash_password_does_not_accept_password_argument() -> None:
    with pytest.raises(SystemExit) as captured:
        main(["auth-hash-password", "not-a-secret"])

    assert captured.value.code == 2
