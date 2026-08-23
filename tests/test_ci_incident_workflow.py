from pathlib import Path


WORKFLOW = Path(".github/workflows/incident-alert.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_incident_workflow_has_bounded_triggers_and_permissions() -> None:
    text = _workflow_text()

    assert "workflow_run:" in text
    assert 'workflows: ["DevRadar CI"]' in text
    assert "branches: [main]" in text
    assert "types: [completed]" in text
    assert "workflow_dispatch:" in text
    assert "contents: read" in text
    assert "issues: write" in text
    assert "actions/checkout" not in text
    assert "download-artifact" not in text


def test_incident_workflow_routes_only_safe_metadata() -> None:
    text = _workflow_text()

    for conclusion in ("failure", "cancelled", "timed_out", "action_required"):
        assert f"github.event.workflow_run.conclusion == '{conclusion}'" in text
    assert "github.event.workflow_run.event == 'push'" in text
    assert "gh issue create" in text
    assert '--assignee "$REPOSITORY_OWNER"' in text
    assert "RUN_URL" in text
    assert "HEAD_SHA" in text
    assert "secrets." not in text
