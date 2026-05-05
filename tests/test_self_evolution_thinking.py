"""Tests for read-only self-evolution thinking candidate generation."""

import json

from code_modification.thinking import (
    THINKING_JOB_NAME,
    ThinkingConfig,
    find_thinking_job,
    load_thinking_config,
    run_self_evolution_thinking,
)
from tools.code_modification_tool import self_evolution_thinking


def test_default_thinking_config_is_disabled():
    """Scheduled thinking must be opt-in."""
    config = load_thinking_config({})

    assert config.enabled is False
    assert config.schedule == "every 7d"
    assert config.max_candidates == 5
    assert config.include_recent_sessions is False


def test_run_once_writes_no_candidate_report(tmp_path):
    """A run with no signal still writes a traceable local report."""
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    report = run_self_evolution_thinking(
        project_root,
        config=ThinkingConfig(include_git_history=False),
    )

    assert report.state.status == "no_candidates"
    assert report.state.candidate_count == 0
    assert report.report_path.exists()
    assert report.candidates_path.exists()
    assert report.state_path.exists()
    assert "advisory only" in report.report_path.read_text(encoding="utf-8")


def test_run_once_finds_failed_verification_candidate(tmp_path):
    """Existing verification failures become advisory candidates, not changes."""
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()
    verification_path = (
        project_root.parent
        / "self-evolution"
        / "tasks"
        / "task-1"
        / "verification.md"
    )
    verification_path.parent.mkdir(parents=True)
    verification_path.write_text("status: verification_failed\n", encoding="utf-8")

    report = run_self_evolution_thinking(
        project_root,
        config=ThinkingConfig(include_git_history=False),
    )

    payload = json.loads(report.candidates_path.read_text(encoding="utf-8"))
    assert report.state.status == "candidates_found"
    assert payload["candidates"][0]["title"] == (
        "Investigate failed self-evolution verification"
    )
    assert payload["candidates"][0]["recommended_next_step"] == "create_approval_plan"


def test_tool_run_once_returns_report_paths(tmp_path):
    """The tool wrapper should expose the generated report paths as JSON."""
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    result = json.loads(
        self_evolution_thinking("run_once", project_root=str(project_root))
    )

    assert result["success"] is True
    assert result["action"] == "run_once"
    assert result["status"] == "no_candidates"
    assert result["report_path"].endswith("thinking-report.md")


def test_enable_updates_single_cron_job_and_disable_pauses_it(tmp_path, monkeypatch):
    """Enabling should update the dedicated job instead of creating duplicates."""
    _redirect_cron_storage(tmp_path, monkeypatch)
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    first = json.loads(
        self_evolution_thinking(
            "enable",
            schedule="every 2h",
            max_candidates=2,
            project_root=str(project_root),
        )
    )
    second = json.loads(
        self_evolution_thinking(
            "enable",
            schedule="every 3h",
            project_root=str(project_root),
        )
    )
    job = find_thinking_job()

    assert first["success"] is True
    assert second["success"] is True
    assert first["job"]["id"] == second["job"]["id"]
    assert job is not None
    assert job["name"] == THINKING_JOB_NAME
    assert job["schedule_display"] == "every 180m"

    disabled = json.loads(self_evolution_thinking("disable", project_root=str(project_root)))

    assert disabled["success"] is True
    assert disabled["config"]["enabled"] is False
    assert disabled["job"]["state"] == "paused"


def _redirect_cron_storage(tmp_path, monkeypatch):
    """Point cron storage at the pytest temp directory after HERMES_HOME is set."""
    import cron.jobs as jobs_module

    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs_module, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_module, "JOBS_FILE", cron_dir / "jobs.json")
    monkeypatch.setattr(jobs_module, "OUTPUT_DIR", cron_dir / "output")
