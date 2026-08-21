from __future__ import annotations

import json
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

import devradar.intelligence.deepseek_spike as deepseek_spike
from devradar.intelligence.deepseek_spike import (
    API_KEY_ENV,
    API_URL,
    MODEL,
    DeepSeekSpikeError,
    _load_local_api_key,
    _request_payload,
    _safe_provider_response,
    main,
    run_development_spike,
)
from devradar.intelligence.evaluation import load_evaluation_dataset

DATASET_PATH = Path(__file__).parent / "fixtures" / "ai" / "job_extraction_eval_v1.json"


class _Headers:
    @staticmethod
    def get_content_type() -> str:
        return "application/json"


class _Response:
    status = 200
    headers = _Headers()

    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def _provider_payload(content: str) -> dict[str, Any]:
    return {
        "id": "spike-response",
        "model": MODEL,
        "system_fingerprint": "test-fingerprint",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {
            "prompt_tokens": 20,
            "prompt_cache_hit_tokens": 4,
            "prompt_cache_miss_tokens": 16,
            "completion_tokens": 12,
            "total_tokens": 32,
        },
    }


def test_request_payload_is_non_thinking_json_without_tools() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    payload = _request_payload(dataset.cases[0])

    assert payload["model"] == MODEL
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert "tools" not in payload
    assert "json" in payload["messages"][0]["content"].lower()  # type: ignore[index]


def test_provider_response_is_validated_and_key_is_only_in_auth_header() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = dataset.cases[0]
    content = case.expected.model_dump_json(by_alias=True)
    captured: dict[str, str] = {}

    def opener(request: Any, *, timeout: float) -> _Response:
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = request.data.decode("utf-8")
        assert timeout > 0
        return _Response(_provider_payload(content))

    response, extraction = _safe_provider_response(
        case=case,
        api_key="unit-test-secret",
        opener=opener,
    )

    assert response.model == MODEL
    assert extraction == case.expected
    assert captured["authorization"] == "Bearer unit-test-secret"
    assert "unit-test-secret" not in captured["body"]


def test_provider_rejects_evidence_not_present_in_input() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = dataset.cases[0]
    payload = json.loads(case.expected.model_dump_json(by_alias=True))
    payload["skills"][0]["evidence"] = "not present"

    with pytest.raises(DeepSeekSpikeError, match="absent from the input"):
        _safe_provider_response(
            case=case,
            api_key="unit-test-secret",
            opener=lambda *_args, **_kwargs: _Response(_provider_payload(json.dumps(payload))),
        )


def test_provider_http_error_is_sanitized() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)

    def opener(*_args: object, **_kwargs: object) -> _Response:
        raise HTTPError(API_URL, 429, "secret body should not escape", Message(), None)

    with pytest.raises(DeepSeekSpikeError) as captured:
        _safe_provider_response(
            case=dataset.cases[0],
            api_key="unit-test-secret",
            opener=opener,
        )

    assert captured.value.code == "provider_http_error"
    assert "secret body" not in str(captured.value)
    assert "unit-test-secret" not in str(captured.value)


def test_development_spike_never_calls_held_out_and_reports_no_content() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    development = tuple(case for case in dataset.cases if case.split.value == "development")
    calls = 0

    def opener(request: Any, *, timeout: float) -> _Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.data.decode("utf-8"))
        input_text = body["messages"][1]["content"]
        case = next(case for case in development if case.input.title in input_text)
        return _Response(_provider_payload(case.expected.model_dump_json(by_alias=True)))

    report = run_development_spike(
        dataset,
        api_key="unit-test-secret",
        repeats=1,
        opener=opener,
        clock=iter(range(100)).__next__,
    )

    assert calls == len(development)
    assert report.cases == len(development)
    assert report.requests == len(development)
    assert report.valid_responses == len(development)
    assert report.exact_matches == len(development)
    assert all(run.case_id.startswith("dev-") for run in report.runs)
    assert API_KEY_ENV == "DEVRADAR_DEEPSEEK_API_KEY"


def test_spike_cli_fails_closed_without_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setattr(deepseek_spike, "LOCAL_ENV_PATH", tmp_path / ".env.local")

    assert main([]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "error": {
            "code": "api_key_missing",
            "message": "DeepSeek spike could not start or complete safely.",
        }
    }
    assert captured.out == ""


def test_local_env_loader_reads_only_exact_key_and_supports_quotes(tmp_path: Path) -> None:
    local_env = tmp_path / ".env.local"
    local_env.write_text(
        "IGNORED=value\nDEVRADAR_DEEPSEEK_API_KEY='unit-test-secret'\n",
        encoding="utf-8",
    )

    assert _load_local_api_key(local_env) == "unit-test-secret"


def test_local_env_loader_rejects_duplicate_key_without_exposing_values(tmp_path: Path) -> None:
    local_env = tmp_path / ".env.local"
    local_env.write_text(
        "DEVRADAR_DEEPSEEK_API_KEY=first-secret\nDEVRADAR_DEEPSEEK_API_KEY=second-secret\n",
        encoding="utf-8",
    )

    with pytest.raises(DeepSeekSpikeError) as captured:
        _load_local_api_key(local_env)

    assert captured.value.code == "local_env_invalid"
    assert "first-secret" not in str(captured.value)
    assert "second-secret" not in str(captured.value)
