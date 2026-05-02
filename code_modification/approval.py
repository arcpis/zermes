"""Approval planning for self-evolution requests.

The functions here prepare a user-reviewable plan from a natural-language
change request. They may write audit documents, but they never modify product
code or create git branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .governance import (
    TaskRecordLayout,
    build_development_branch_name,
    build_task_record_layout,
    make_task_id,
)


@dataclass(frozen=True)
class ApprovalPlan:
    """A complete pre-change plan that must be approved before implementation."""

    task_id: str
    requirement_summary: str
    boundary: str
    affected_areas: tuple[str, ...]
    proposed_approach: str
    tasks: tuple[str, ...]
    difficulty: str
    time_estimate: str
    risks: tuple[str, ...]
    test_plan: tuple[str, ...]
    open_questions: tuple[str, ...]
    recommend_execution: bool
    development_branch: str


def build_approval_plan(
    requirement: str,
    project_root: str | Path,
    *,
    context: str = "",
    affected_areas: tuple[str, ...] = (),
    now: datetime | None = None,
) -> tuple[ApprovalPlan, TaskRecordLayout]:
    """Build a review plan and audit layout for a change request."""
    clean_requirement = requirement.strip()
    task_id = make_task_id(clean_requirement, now=now)
    layout = build_task_record_layout(project_root, task_id)
    open_questions = _find_open_questions(clean_requirement)
    recommend_execution = not open_questions
    boundary = (
        "Product code changes, git branch creation, commits, builds, or restarts "
        "are forbidden before explicit user approval."
    )
    plan = ApprovalPlan(
        task_id=task_id,
        requirement_summary=clean_requirement or "No requirement provided.",
        boundary=boundary,
        affected_areas=affected_areas or ("To be confirmed by focused code reading.",),
        proposed_approach=_build_approach(clean_requirement, context, recommend_execution),
        tasks=_build_tasks(recommend_execution),
        difficulty="Unknown until focused code analysis is complete.",
        time_estimate="Unknown until focused code analysis is complete.",
        risks=(
            "Incorrect scope if the affected modules are not confirmed.",
            "Regression risk if related tests are missing or not run.",
        ),
        test_plan=(
            "Identify existing tests that cover the affected behavior.",
            "Add or update focused tests before implementation when feasible.",
            "Run the smallest relevant test set before reporting success.",
        ),
        open_questions=open_questions,
        recommend_execution=recommend_execution,
        development_branch=build_development_branch_name(task_id),
    )
    return plan, layout


def write_approval_documents(plan: ApprovalPlan, layout: TaskRecordLayout) -> None:
    """Write the pre-change plan and approval request into the audit record."""
    layout.task_dir.mkdir(parents=True, exist_ok=True)
    layout.plan_path.write_text(render_plan_markdown(plan), encoding="utf-8")
    layout.approval_path.write_text(render_approval_markdown(plan), encoding="utf-8")


def render_plan_markdown(plan: ApprovalPlan) -> str:
    """Render a plan for human review."""
    return "\n".join(
        [
            "# Pre-Change Plan",
            "",
            f"- Task ID: `{plan.task_id}`",
            f"- Requirement: {plan.requirement_summary}",
            f"- Recommended execution: `{str(plan.recommend_execution).lower()}`",
            f"- Development branch: `{plan.development_branch}`",
            "",
            "## Boundary",
            "",
            plan.boundary,
            "",
            "## Affected Areas",
            "",
            *_bullet_lines(plan.affected_areas),
            "",
            "## Proposed Approach",
            "",
            plan.proposed_approach,
            "",
            "## Tasks",
            "",
            *_bullet_lines(plan.tasks),
            "",
            "## Estimates",
            "",
            f"- Difficulty: {plan.difficulty}",
            f"- Time: {plan.time_estimate}",
            "",
            "## Risks",
            "",
            *_bullet_lines(plan.risks),
            "",
            "## Test Plan",
            "",
            *_bullet_lines(plan.test_plan),
            "",
            "## Open Questions",
            "",
            *_bullet_lines(plan.open_questions or ("None.",)),
            "",
        ]
    )


def render_approval_markdown(plan: ApprovalPlan) -> str:
    """Render the explicit approval request."""
    if plan.recommend_execution:
        approval_text = "Please approve before implementation starts."
    else:
        approval_text = "Please answer the open questions before implementation starts."
    return "\n".join(
        [
            "# Approval Request",
            "",
            approval_text,
            "",
            f"- Task ID: `{plan.task_id}`",
            f"- Development branch after approval: `{plan.development_branch}`",
            "- Product code changes before approval: `forbidden`",
            "",
        ]
    )


def _find_open_questions(requirement: str) -> tuple[str, ...]:
    if not requirement:
        return ("What change should Hermes implement?",)
    if len(requirement.split()) < 4:
        return ("Please describe the target behavior and expected outcome.",)
    return ()


def _build_approach(requirement: str, context: str, recommend_execution: bool) -> str:
    if not recommend_execution:
        return "Clarify the request before reading code or planning implementation."
    context_note = f" Context: {context.strip()}" if context.strip() else ""
    return (
        "Perform focused code reading, confirm the affected modules, refine the task "
        f"breakdown, request approval, and only then implement the change.{context_note}"
    )


def _build_tasks(recommend_execution: bool) -> tuple[str, ...]:
    if not recommend_execution:
        return ("Collect missing requirement details.", "Regenerate the approval plan.")
    return (
        "Confirm affected modules with focused code reading.",
        "Refine the implementation plan and tests.",
        "Request explicit user approval.",
        "After approval, implement changes in small commits.",
    )


def _bullet_lines(items: tuple[str, ...]) -> list[str]:
    return [f"- {item}" for item in items]
