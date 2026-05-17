"""Tests for install-local low-token analysis context building."""

import json

from code_modification.token_strategy import (
    AnalysisBudget,
    AnalysisHints,
    build_analysis_context,
    collect_structure_sources,
    get_analysis_cache_dir,
    summarize_repository_file,
)


def test_analysis_cache_uses_install_data_workspace(tmp_path):
    """The stage 7 cache belongs to install-local runtime data."""
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()
    prefix = tmp_path / "zermes"

    assert get_analysis_cache_dir(project_root, install_prefix=prefix) == (
        prefix / "data" / "self-evolution" / "analysis-cache"
    )


def test_collect_structure_sources_uses_repository_documents(tmp_path):
    """Repository documentation should be preferred as a low-cost entry point."""
    project_root = tmp_path / "hermes-agent"
    _write(project_root / "AGENTS.md", "# Rules\n")
    _write(project_root / "README.md", "# Hermes\n")
    _write(project_root / "RELEASE_v1.0.0.md", "# Release\n")
    _write(project_root / "toolsets.py", "CONFIGURABLE_TOOLSETS = {}\n")

    sources = collect_structure_sources(project_root)
    paths = {source.relative_path for source in sources}

    assert {"AGENTS.md", "README.md", "RELEASE_v1.0.0.md", "toolsets.py"} <= paths


def test_build_analysis_context_writes_reusable_task_summaries(tmp_path):
    """A context run should write reusable summaries for later task steps."""
    project_root = tmp_path / "hermes-agent"
    _write(project_root / "AGENTS.md", "# Rules\nUse focused tests.\n")
    _write(project_root / "README.md", "# Hermes\nUser guide.\n")
    _write(project_root / "tools" / "code_modification_tool.py", "def complete_code_task():\n    pass\n")

    context = build_analysis_context(
        project_root,
        purpose="approval",
        install_prefix=tmp_path / "zermes",
        hints=AnalysisHints(
            requirement="Update a tool schema and document the user-facing command.",
            explicit_paths=("tools/code_modification_tool.py",),
        ),
    )

    assert context.context_state_path.startswith(str(tmp_path / "zermes" / "data"))
    assert context.task_context_summary_path.startswith(str(tmp_path / "zermes" / "data"))
    assert context.docs_summary_path.startswith(str(tmp_path / "zermes" / "data"))
    assert "README.md" in context.documentation_updates
    assert "AGENTS.md" in context.documentation_updates
    assert json.loads(_read(context.docs_summary_path))


def test_summary_cache_is_reused_for_unchanged_file(tmp_path):
    """Unchanged files should hit the summary cache in later reads."""
    project_root = tmp_path / "hermes-agent"
    target = project_root / "README.md"
    _write(target, "# Hermes\nReusable summary.\n")
    cache_root = get_analysis_cache_dir(project_root, install_prefix=tmp_path / "zermes")

    first = summarize_repository_file(target, project_root, cache_root, source_type="documentation")
    second = summarize_repository_file(target, project_root, cache_root, source_type="documentation")

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True


def test_context_rejects_paths_outside_project_root(tmp_path):
    """Explicit hints outside project_root should be ignored safely."""
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()
    outside = tmp_path / "README.md"
    _write(outside, "# Outside\n")

    context = build_analysis_context(
        project_root,
        purpose="thinking",
        install_prefix=tmp_path / "zermes",
        hints=AnalysisHints(explicit_paths=("../README.md",)),
        budget=AnalysisBudget(
            max_sources=5,
            max_file_summaries=2,
            max_detail_snippets=0,
            max_total_chars=10_000,
        ),
    )

    assert all(".." not in source.relative_path for source in context.selected_sources)
    assert context.project_root == str(project_root.resolve())


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(path):
    return open(path, encoding="utf-8").read()
