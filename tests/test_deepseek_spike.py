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
    CANONICALIZATION_VERSION,
    MODEL,
    DeepSeekSpikeError,
    _load_local_api_key,
    _request_payload,
    _safe_provider_response,
    _score_extraction,
    main,
    run_development_spike,
    run_held_out_evaluation,
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
    assert report.schema_evidence_acceptance_rate == 1.0
    assert report.skill_f1 == 1.0
    assert report.complete_accepted_rate == 1.0
    assert report.canonicalization_version == CANONICALIZATION_VERSION
    assert all(run.case_id.startswith("dev-") for run in report.runs)
    assert API_KEY_ENV == "DEVRADAR_DEEPSEEK_API_KEY"


def test_held_out_evaluation_is_explicit_and_keeps_split_boundary() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    held_out = tuple(case for case in dataset.cases if case.split.value == "held_out")

    def opener(request: Any, *, timeout: float) -> _Response:
        body = json.loads(request.data.decode("utf-8"))
        input_text = body["messages"][1]["content"]
        case = next(case for case in held_out if case.input.title in input_text)
        return _Response(_provider_payload(case.expected.model_dump_json(by_alias=True)))

    report = run_held_out_evaluation(
        dataset,
        api_key="unit-test-secret",
        repeats=1,
        opener=opener,
        clock=iter(range(100)).__next__,
    )

    assert report.split == "held_out"
    assert report.cases == len(held_out)
    assert report.requests == len(held_out)
    assert all(run.case_id.startswith("held-") for run in report.runs)


def test_provider_canonicalizes_skill_alias_and_deterministic_fields() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = next(case for case in dataset.cases if case.id == "held-en-dotnet-004")
    content = json.dumps(
        {
            "levels": ["junior"],
            "experience": {"minimumYears": 99, "maximumYears": 100},
            "salary": {"minimum": 1, "maximum": 2, "currency": "USD", "period": "year"},
            "location": {"city": "Hanoi", "province": "Hanoi", "workMode": "remote"},
            "skills": [
                {"name": "C sharp", "requirementType": "required", "evidence": "C#"},
                {"name": ".NET", "requirementType": "required", "evidence": ".NET"},
                {"name": "SQL", "requirementType": "required", "evidence": "SQL"},
                {"name": "Azure", "requirementType": "optional", "evidence": "Azure"},
            ],
        }
    )

    _response, extraction = _safe_provider_response(
        case=case,
        api_key="unit-test-secret",
        opener=lambda *_args, **_kwargs: _Response(_provider_payload(content)),
    )

    assert extraction == case.expected


def test_provider_rejects_invalid_scalar_shape_before_canonicalization() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = dataset.cases[0]
    payload = json.loads(case.expected.model_dump_json(by_alias=True))
    payload["experience"]["minimumYears"] = {"unexpected": "object"}

    with pytest.raises(DeepSeekSpikeError) as captured:
        _safe_provider_response(
            case=case,
            api_key="unit-test-secret",
            opener=lambda *_args, **_kwargs: _Response(_provider_payload(json.dumps(payload))),
        )
    assert captured.value.code.startswith("provider_extraction_shape_invalid:")


def test_provider_uses_deterministic_salary_scale_and_ambiguity_rules() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = next(case for case in dataset.cases if case.id == "held-mixed-go-platform-003")
    content = json.dumps(
        {
            "levels": [],
            "experience": {"minimumYears": None, "maximumYears": None},
            "salary": {"minimum": 40, "maximum": 60, "currency": "VND", "period": "month"},
            "location": {"city": None, "province": None, "workMode": None},
            "skills": [
                {"name": "Go", "requirementType": "required", "evidence": "Go"},
                {
                    "name": "Apache Kafka",
                    "requirementType": "required",
                    "evidence": "Apache Kafka",
                },
                {"name": "Redis", "requirementType": "optional", "evidence": "Redis"},
            ],
        }
    )

    _response, extraction = _safe_provider_response(
        case=case,
        api_key="unit-test-secret",
        opener=lambda *_args, **_kwargs: _Response(_provider_payload(content)),
    )

    assert extraction == case.expected


def test_scoring_accepts_different_supported_evidence_for_same_skill_labels() -> None:
    case = load_evaluation_dataset(DATASET_PATH).cases[0]
    first_skill = case.expected.skills[0].model_copy(update={"evidence": "Yêu cầu: Python"})
    actual = case.expected.model_copy(update={"skills": (first_skill, *case.expected.skills[1:])})

    assert _score_extraction(actual, case.expected).exact_match is True


def test_rejected_extraction_preserves_provider_usage_and_cost() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)

    report = run_development_spike(
        dataset,
        api_key="unit-test-secret",
        repeats=1,
        opener=lambda *_args, **_kwargs: _Response(_provider_payload("{}")),
        clock=iter(range(100)).__next__,
    )

    assert report.valid_responses == 0
    assert report.prompt_tokens == 20 * report.requests
    assert report.completion_tokens == 12 * report.requests
    assert report.estimated_cost_usd == pytest.approx(0.00027528)
    assert report.schema_evidence_acceptance_rate == 0.0
    assert report.skill_recall == 0.0
    assert all(
        run.error_code is not None
        and run.error_code.startswith(
            ("provider_extraction_shape_invalid:", "provider_extraction_schema_invalid:")
        )
        for run in report.runs
    )


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
