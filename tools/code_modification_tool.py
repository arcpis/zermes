#!/usr/bin/env python3
"""Self-evolution code modification planning tool."""

from __future__ import annotations

import os
from pathlib import Path

from code_modification.approval import build_approval_plan, write_approval_documents
from tools.registry import registry, tool_error, tool_result


def complete_code_task(
    requirement: str,
    *,
    context: str = "",
    affected_areas: list[str] | None = None,
    project_root: str | None = None,
) -> str:
    """Create a pre-change approval plan without modifying product code."""
    clean_requirement = str(requirement or "").strip()
    if not clean_requirement:
        return tool_error("requirement is required.")

    clean_affected_areas = _clean_affected_areas(affected_areas)
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())

    plan, layout = build_approval_plan(
        clean_requirement,
        root,
        context=str(context or ""),
        affected_areas=tuple(clean_affected_areas),
    )
    write_approval_documents(plan, layout)

    return tool_result(
        success=True,
        task_id=plan.task_id,
        recommend_execution=plan.recommend_execution,
        open_questions=list(plan.open_questions),
        development_branch=plan.development_branch,
        plan_path=str(layout.plan_path),
        approval_path=str(layout.approval_path),
    )


def _clean_affected_areas(affected_areas: list[str] | None) -> list[str]:
    if affected_areas is None:
        return []
    if not isinstance(affected_areas, list):
        raise TypeError("affected_areas must be a list of strings.")
    return [str(area).strip() for area in affected_areas if str(area).strip()]


def check_code_modification_requirements() -> bool:
    """The approval planner has no external service requirements."""
    return True


COMPLETE_CODE_TASK_SCHEMA = {
    "name": "complete_code_task",
    "description": (
        "Create a self-evolution pre-change approval plan for a requested code "
        "change. Use this when the user asks Hermes to add a tool, fix a bug, "
        "optimize performance, improve interaction flow, or otherwise modify "
        "the codebase. Before calling, perform low-token, focused code reading "
        "only as needed, then pass confirmed module/file scope in affected_areas "
        "and a concise context summary. This tool only writes self-evolution "
        "audit documents; it must not implement code changes, create branches, "
        "run git commands, or execute builds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "requirement": {
                "type": "string",
                "description": "Natural-language code modification request to analyze.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional concise summary from focused code reading, recent "
                    "failures, user feedback, or existing self-evolution docs."
                ),
            },
            "affected_areas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of confirmed modules, files, or subsystems "
                    "likely affected by the requested change."
                ),
            },
            "project_root": {
                "type": "string",
                "description": (
                    "Optional project root. Defaults to the current working directory; "
                    "the self-evolution workspace is placed next to this root."
                ),
            },
        },
        "required": ["requirement"],
    },
}


registry.register(
    name="complete_code_task",
    toolset="code_modification",
    schema=COMPLETE_CODE_TASK_SCHEMA,
    handler=lambda args, **kw: complete_code_task(
        requirement=args.get("requirement", ""),
        context=args.get("context", ""),
        affected_areas=args.get("affected_areas"),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🧭",
)
