"""Read-only self-evolution thinking support.

This module powers the scheduled and manual "thinking" pass for Hermes'
self-evolution workflow. It is deliberately conservative: it can write candidate
reports under the self-evolution workspace, but it must not edit product code,
create branches, commit, merge, or run verification commands.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any

from code_modification.governance import get_evolution_workspace
from hermes_cli.config import load_config, save_config


CANDIDATES_DIR_NAME = "candidates"
THINKING_JOB_NAME = "self-evolution-thinking"
THINKING_CONFIG_PATH = ("self_evolution", "thinking")
DEFAULT_THINKING_SCHEDULE = "every 7d"
DEFAULT_MAX_CANDIDATES = 5


class SelfEvolutionThinkingError(RuntimeError):
    """Raised when self-evolution thinking cannot complete safely."""


@dataclass(frozen=True)
class ThinkingConfig:
    """User-configurable options for scheduled self-evolution thinking."""

    enabled: bool = False
    schedule: str = DEFAULT_THINKING_SCHEDULE
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    include_recent_sessions: bool = False
    include_test_failures: bool = True
    include_git_history: bool = True
    delivery: str = "local"


@dataclass(frozen=True)
class ImprovementCandidate:
    """A possible improvement discovered during a read-only thinking pass."""

    id: str
    title: str
    summary: str
    evidence: list[str]
    affected_areas: list[str]
    risk_level: str
    recommended_next_step: str
    suggested_requirement: str
    test_ideas: list[str]


@dataclass(frozen=True)
class ThinkingRunState:
    """Machine-readable status for one thinking run."""

    run_id: str
    trigger: str
    status: str
    started_at: str
    completed_at: str
    candidate_count: int
    blocked_reason: str
    sources_read: list[str]
    sources_skipped: list[str]
    dirty_worktree: bool


@dataclass(frozen=True)
class ThinkingReport:
    """Full result of one self-evolution thinking pass."""

    state: ThinkingRunState
    candidates: list[ImprovementCandidate]
    report_path: Path
    candidates_path: Path
    state_path: Path
    index_path: Path


def default_thinking_config_dict() -> dict[str, Any]:
    """Return the serializable default config block for self-evolution thinking."""
    return asdict(ThinkingConfig())


def load_thinking_config(config: dict[str, Any] | None = None) -> ThinkingConfig:
    """Load the thinking config from a Hermes config dict or the profile config."""
    source = config if config is not None else load_config()
    current: Any = source
    for key in THINKING_CONFIG_PATH:
        current = current.get(key, {}) if isinstance(current, dict) else {}
    return _coerce_thinking_config(current if isinstance(current, dict) else {})


def update_thinking_config(updates: dict[str, Any]) -> ThinkingConfig:
    """Persist a partial update to the thinking config and return the new value."""
    config = load_config()
    section = _ensure_nested_dict(config, THINKING_CONFIG_PATH)
    section.update(updates)
    save_config(config)
    return load_thinking_config(config)


def run_self_evolution_thinking(
    project_root: str | Path,
    *,
    trigger: str = "manual",
    config: ThinkingConfig | None = None,
) -> ThinkingReport:
    """Generate a read-only candidate report for the given project root."""
    root = Path(project_root).expanduser().resolve()
    thinking_config = config or load_thinking_config()
    started_at = _utc_timestamp()
    run_id = f"thinking-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
    run_dir = get_candidates_dir(root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    sources_read: list[str] = []
    sources_skipped: list[str] = []
    dirty_worktree = _is_git_worktree_dirty(root)
    candidates = _discover_candidates(
        root,
        thinking_config,
        sources_read=sources_read,
        sources_skipped=sources_skipped,
    )
    candidates = candidates[: thinking_config.max_candidates]
    status = "candidates_found" if candidates else "no_candidates"
    state = ThinkingRunState(
        run_id=run_id,
        trigger=trigger,
        status=status,
        started_at=started_at,
        completed_at=_utc_timestamp(),
        candidate_count=len(candidates),
        blocked_reason="",
        sources_read=sources_read,
        sources_skipped=sources_skipped,
        dirty_worktree=dirty_worktree,
    )

    report = ThinkingReport(
        state=state,
        candidates=candidates,
        report_path=run_dir / "thinking-report.md",
        candidates_path=run_dir / "candidates.json",
        state_path=run_dir / "run-state.json",
        index_path=get_candidates_dir(root) / "index.md",
    )
    write_thinking_report(report)
    return report


def describe_self_evolution_thinking(project_root: str | Path) -> dict[str, Any]:
    """Return config, cron job state, and the latest local thinking run."""
    root = Path(project_root).expanduser().resolve()
    latest = _latest_run_dir(get_candidates_dir(root))
    job = find_thinking_job()
    config = load_thinking_config()
    return {
        "config": asdict(config),
        "job": _summarize_job(job) if job else None,
        "latest_run": str(latest) if latest else None,
        "candidates_dir": str(get_candidates_dir(root)),
    }


def enable_self_evolution_thinking(
    project_root: str | Path,
    *,
    schedule: str | None = None,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    """Enable scheduled thinking and create or update its dedicated cron job."""
    updates: dict[str, Any] = {"enabled": True}
    if schedule:
        updates["schedule"] = str(schedule).strip()
    if max_candidates is not None:
        updates["max_candidates"] = _positive_int(max_candidates, DEFAULT_MAX_CANDIDATES)
    config = update_thinking_config(updates)
    job = ensure_thinking_job(Path(project_root).expanduser().resolve(), config)
    return {"config": asdict(config), "job": _summarize_job(job)}


def disable_self_evolution_thinking() -> dict[str, Any]:
    """Disable scheduled thinking and pause the dedicated cron job if present."""
    from cron.jobs import pause_job

    config = update_thinking_config({"enabled": False})
    job = find_thinking_job()
    if job:
        job = pause_job(job["id"], reason="Self-evolution thinking disabled")
    return {"config": asdict(config), "job": _summarize_job(job) if job else None}


def ensure_thinking_job(project_root: Path, config: ThinkingConfig) -> dict[str, Any]:
    """Create or update the single cron job used for scheduled thinking."""
    from cron.jobs import create_job, update_job

    prompt = build_thinking_cron_prompt(project_root)
    existing = find_thinking_job()
    updates = {
        "name": THINKING_JOB_NAME,
        "prompt": prompt,
        "schedule": config.schedule,
        "deliver": "local",
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
    }
    if existing:
        updated = update_job(existing["id"], updates)
        if not updated:
            raise SelfEvolutionThinkingError("Failed to update self-evolution thinking job.")
        return updated
    return create_job(
        prompt=prompt,
        schedule=config.schedule,
        name=THINKING_JOB_NAME,
        deliver="local",
    )


def find_thinking_job() -> dict[str, Any] | None:
    """Return the dedicated self-evolution thinking cron job, if it exists."""
    from cron.jobs import list_jobs

    for job in list_jobs(include_disabled=True):
        if job.get("name") == THINKING_JOB_NAME:
            return job
    return None


def build_thinking_cron_prompt(project_root: Path) -> str:
    """Build the safe cron prompt that asks the agent to run one thinking pass."""
    return (
        "Run one scheduled self-evolution thinking pass for this repository.\n"
        f"Project root: {project_root}\n"
        "Call self_evolution_thinking with action='run_once' and the project_root above.\n"
        "Only generate local candidate reports. Do not edit product code, create "
        "branches, commit, merge, deploy, or call approved execution tools."
    )


def write_thinking_report(report: ThinkingReport) -> None:
    """Write the Markdown report, JSON candidates, run state, and index entry."""
    report.report_path.write_text(_format_report_markdown(report), encoding="utf-8")
    report.candidates_path.write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": report.state.run_id,
                "candidates": [asdict(candidate) for candidate in report.candidates],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report.state_path.write_text(
        json.dumps(asdict(report.state), indent=2) + "\n",
        encoding="utf-8",
    )
    report.index_path.parent.mkdir(parents=True, exist_ok=True)
    with report.index_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"- {report.state.completed_at} `{report.state.run_id}`: "
            f"{report.state.status}, {report.state.candidate_count} candidates "
            f"({report.report_path})\n"
        )


def get_candidates_dir(project_root: str | Path) -> Path:
    """Return the directory that stores self-evolution thinking candidates."""
    return get_evolution_workspace(project_root) / CANDIDATES_DIR_NAME


def _discover_candidates(
    project_root: Path,
    config: ThinkingConfig,
    *,
    sources_read: list[str],
    sources_skipped: list[str],
) -> list[ImprovementCandidate]:
    candidates: list[ImprovementCandidate] = []
    workspace = get_evolution_workspace(project_root)

    if config.include_test_failures:
        candidates.extend(_candidates_from_verification_records(workspace, sources_read))
    else:
        sources_skipped.append("verification records: disabled by config")

    if config.include_git_history:
        sources_read.append("git status --porcelain")
    else:
        sources_skipped.append("git history: disabled by config")

    if not config.include_recent_sessions:
        sources_skipped.append("recent sessions: disabled by config")

    return _deduplicate_candidates(candidates)


def _candidates_from_verification_records(
    workspace: Path,
    sources_read: list[str],
) -> list[ImprovementCandidate]:
    tasks_dir = workspace / "tasks"
    if not tasks_dir.exists():
        return []
    candidates: list[ImprovementCandidate] = []
    for verification_path in tasks_dir.glob("*/verification.md"):
        text = verification_path.read_text(encoding="utf-8", errors="replace").lower()
        sources_read.append(str(verification_path))
        if "verification_failed" in text or "blocked" in text or "failed" in text:
            candidates.append(
                ImprovementCandidate(
                    id=f"candidate-{len(candidates) + 2:03d}",
                    title="Investigate failed self-evolution verification",
                    summary=(
                        "A previous self-evolution verification record contains a "
                        "failure or blocked state that should be triaged before more "
                        "automation is added."
                    ),
                    evidence=[f"{verification_path} contains a failure or blocked state."],
                    affected_areas=["code_modification", "tests"],
                    risk_level="medium",
                    recommended_next_step="create_approval_plan",
                    suggested_requirement=(
                        "Investigate and fix the failed or blocked self-evolution "
                        "verification record."
                    ),
                    test_ideas=["Re-run the verification command recorded for the task."],
                )
            )
    return candidates


def _deduplicate_candidates(
    candidates: list[ImprovementCandidate],
) -> list[ImprovementCandidate]:
    unique: list[ImprovementCandidate] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for candidate in candidates:
        key = (candidate.title, tuple(candidate.affected_areas))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return [
        ImprovementCandidate(
            id=f"candidate-{index:03d}",
            title=candidate.title,
            summary=candidate.summary,
            evidence=candidate.evidence,
            affected_areas=candidate.affected_areas,
            risk_level=candidate.risk_level,
            recommended_next_step=candidate.recommended_next_step,
            suggested_requirement=candidate.suggested_requirement,
            test_ideas=candidate.test_ideas,
        )
        for index, candidate in enumerate(unique, start=1)
    ]


def _format_report_markdown(report: ThinkingReport) -> str:
    lines = [
        f"# Self-Evolution Thinking Report: {report.state.run_id}",
        "",
        "## Status",
        "",
        f"- Trigger: {report.state.trigger}",
        f"- Status: {report.state.status}",
        f"- Started at: {report.state.started_at}",
        f"- Completed at: {report.state.completed_at}",
        f"- Dirty worktree: {str(report.state.dirty_worktree).lower()}",
        "",
        "## Candidates",
        "",
    ]
    if not report.candidates:
        lines.append("No improvement candidates were found in the configured sources.")
    for candidate in report.candidates:
        lines.extend(
            [
                f"### {candidate.id}: {candidate.title}",
                "",
                candidate.summary,
                "",
                f"- Risk: {candidate.risk_level}",
                f"- Next step: {candidate.recommended_next_step}",
                f"- Suggested requirement: {candidate.suggested_requirement}",
                f"- Affected areas: {', '.join(candidate.affected_areas)}",
                f"- Evidence: {'; '.join(candidate.evidence)}",
                f"- Test ideas: {'; '.join(candidate.test_ideas)}",
                "",
            ]
        )
    lines.extend(
        [
            "## Sources",
            "",
            "- Read:",
            *[f"  - {source}" for source in report.state.sources_read],
            "- Skipped:",
            *[f"  - {source}" for source in report.state.sources_skipped],
            "",
            "## Safety",
            "",
            "This report is advisory only. It does not approve or execute code changes.",
            "",
        ]
    )
    return "\n".join(lines)


def _coerce_thinking_config(raw: dict[str, Any]) -> ThinkingConfig:
    return ThinkingConfig(
        enabled=bool(raw.get("enabled", False)),
        schedule=str(raw.get("schedule") or DEFAULT_THINKING_SCHEDULE),
        max_candidates=_positive_int(raw.get("max_candidates"), DEFAULT_MAX_CANDIDATES),
        include_recent_sessions=bool(raw.get("include_recent_sessions", False)),
        include_test_failures=bool(raw.get("include_test_failures", True)),
        include_git_history=bool(raw.get("include_git_history", True)),
        delivery=str(raw.get("delivery") or "local"),
    )


def _ensure_nested_dict(config: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    current = config
    for key in path:
        value = current.get(key)
        if not isinstance(value, dict):
            value = {}
            current[key] = value
        current = value
    return current


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _is_git_worktree_dirty(project_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(result.stdout.strip())


def _latest_run_dir(candidates_dir: Path) -> Path | None:
    if not candidates_dir.exists():
        return None
    runs = [path for path in candidates_dir.iterdir() if path.is_dir()]
    return sorted(runs)[-1] if runs else None


def _summarize_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "enabled": job.get("enabled", True),
        "state": job.get("state"),
        "schedule": job.get("schedule_display"),
        "next_run_at": job.get("next_run_at"),
    }


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()
