"""Low-token repository analysis context builder.

The helpers in this module build a compact, reusable context from files inside
one Hermes repository root. They never inspect sibling directories or parent
directories, which keeps self-evolution analysis portable and predictable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Literal


ANALYSIS_CACHE_DIR_NAME = ".hermes-analysis-cache"
DEFAULT_MAX_TEXT_FILE_BYTES = 40_000
DEFAULT_RELEASE_SUMMARY_COUNT = 2
DOCUMENTATION_PATHS = (
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
)
CORE_SOURCE_PATHS = (
    "toolsets.py",
    "model_tools.py",
    "tools/code_modification_tool.py",
)


@dataclass(frozen=True)
class AnalysisBudget:
    """Limits for one bounded analysis pass."""

    max_sources: int
    max_file_summaries: int
    max_detail_snippets: int
    max_total_chars: int
    max_doc_summaries: int = 6
    max_release_files: int = DEFAULT_RELEASE_SUMMARY_COUNT


@dataclass(frozen=True)
class AnalysisHints:
    """Signals that help the context builder focus on relevant repository files."""

    requirement: str = ""
    explicit_paths: tuple[str, ...] = ()
    include_git_history: bool = True
    require_documentation_sync_check: bool = True


@dataclass(frozen=True)
class SourceCandidate:
    """A repository-local source that may be summarized for an analysis pass."""

    relative_path: str
    source_type: str
    priority: int
    reason: str
    estimated_cost: int


@dataclass(frozen=True)
class SelectedSource:
    """A source that was selected and summarized within the current budget."""

    relative_path: str
    source_type: str
    reason: str
    chars_read: int
    cache_hit: bool
    summary_path: str


@dataclass(frozen=True)
class DocumentationSummary:
    """Summary metadata for a user-visible repository documentation file."""

    relative_path: str
    category: str
    title: str
    summary: str
    user_visible: bool
    requires_sync_after_code_change: bool
    size: int
    mtime_ns: int
    cache_hit: bool
    summary_path: str


@dataclass(frozen=True)
class AnalysisContext:
    """Reusable context artifacts written for one analysis run."""

    context_run_id: str
    purpose: str
    project_root: str
    cache_dir: str
    task_context_summary_path: str
    docs_summary_path: str
    context_state_path: str
    selected_sources_path: str
    selected_sources: tuple[SelectedSource, ...]
    skipped_sources: tuple[str, ...]
    documentation_updates: tuple[str, ...]
    cache_hits: int
    budget_exhausted: bool


DEFAULT_THINKING_BUDGET = AnalysisBudget(
    max_sources=20,
    max_file_summaries=8,
    max_detail_snippets=2,
    max_total_chars=80_000,
)
DEFAULT_APPROVAL_BUDGET = AnalysisBudget(
    max_sources=30,
    max_file_summaries=12,
    max_detail_snippets=4,
    max_total_chars=120_000,
)


def get_analysis_cache_dir(project_root: str | Path) -> Path:
    """Return the repository-local directory used for reusable summaries."""
    root = _resolve_project_root(project_root)
    return root / ANALYSIS_CACHE_DIR_NAME


def build_analysis_context(
    project_root: str | Path,
    *,
    purpose: Literal["thinking", "approval"],
    hints: AnalysisHints | None = None,
    budget: AnalysisBudget | None = None,
) -> AnalysisContext:
    """Build and persist a compact context from files inside project_root."""
    root = _resolve_project_root(project_root)
    active_hints = hints or AnalysisHints()
    active_budget = budget or _default_budget_for_purpose(purpose)
    cache_root = get_analysis_cache_dir(root)
    context_run_id = f"context-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
    run_dir = cache_root / "runs" / context_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    candidates = collect_structure_sources(root, active_hints, active_budget)
    selected, skipped, budget_exhausted = select_sources(candidates, active_budget)
    selected_sources: list[SelectedSource] = []
    docs: list[DocumentationSummary] = []
    total_chars = 0

    for candidate in selected:
        summary = summarize_repository_file(
            root / candidate.relative_path,
            root,
            cache_root,
            source_type=candidate.source_type,
        )
        total_chars += summary["chars_read"]
        selected_sources.append(
            SelectedSource(
                relative_path=candidate.relative_path,
                source_type=candidate.source_type,
                reason=candidate.reason,
                chars_read=summary["chars_read"],
                cache_hit=summary["cache_hit"],
                summary_path=summary["summary_path"],
            )
        )
        if candidate.source_type == "documentation":
            docs.append(_documentation_summary_from_payload(summary))
        if total_chars > active_budget.max_total_chars:
            skipped.append("budget_exhausted: max_total_chars reached")
            budget_exhausted = True
            break

    documentation_updates = _suggest_documentation_updates(active_hints, docs)
    docs_summary_path = run_dir / "docs-summary.json"
    selected_sources_path = run_dir / "selected-sources.json"
    task_context_summary_path = run_dir / "task-context-summary.md"
    context_state_path = run_dir / "context-state.json"

    docs_summary_path.write_text(
        json.dumps([asdict(doc) for doc in docs], indent=2) + "\n",
        encoding="utf-8",
    )
    selected_sources_path.write_text(
        json.dumps([asdict(source) for source in selected_sources], indent=2) + "\n",
        encoding="utf-8",
    )
    task_context_summary_path.write_text(
        _format_task_context_summary(
            purpose=purpose,
            selected_sources=selected_sources,
            documentation_updates=documentation_updates,
            skipped_sources=skipped,
        ),
        encoding="utf-8",
    )

    context = AnalysisContext(
        context_run_id=context_run_id,
        purpose=purpose,
        project_root=str(root),
        cache_dir=str(cache_root),
        task_context_summary_path=str(task_context_summary_path),
        docs_summary_path=str(docs_summary_path),
        context_state_path=str(context_state_path),
        selected_sources_path=str(selected_sources_path),
        selected_sources=tuple(selected_sources),
        skipped_sources=tuple(skipped),
        documentation_updates=tuple(documentation_updates),
        cache_hits=sum(1 for source in selected_sources if source.cache_hit),
        budget_exhausted=budget_exhausted,
    )
    context_state_path.write_text(json.dumps(asdict(context), indent=2) + "\n", encoding="utf-8")
    _write_cache_index(cache_root, context)
    return context


def collect_structure_sources(
    project_root: str | Path,
    hints: AnalysisHints | None = None,
    budget: AnalysisBudget | None = None,
) -> list[SourceCandidate]:
    """Collect high-signal repository-local sources without reading full content."""
    root = _resolve_project_root(project_root)
    active_hints = hints or AnalysisHints()
    active_budget = budget or DEFAULT_THINKING_BUDGET
    candidates: list[SourceCandidate] = []
    candidates.extend(_documentation_candidates(root, active_budget))
    candidates.extend(_explicit_path_candidates(root, active_hints))
    candidates.extend(_core_source_candidates(root))
    candidates.extend(_glob_candidates(root, "code_modification/*.py", "core_module", 70))
    candidates.extend(_glob_candidates(root, "tests/self_evolution/test_code_modification_*.py", "test_file", 60))
    thinking_test = root / "tests" / "self_evolution" / "test_self_evolution_thinking.py"
    if thinking_test.exists():
        candidates.append(_source_candidate(root, thinking_test, "test_file", 60, "thinking test"))
    if active_hints.include_git_history:
        candidates.extend(_git_status_candidates(root))
    return _deduplicate_candidates(candidates)


def select_sources(
    candidates: list[SourceCandidate],
    budget: AnalysisBudget,
) -> tuple[list[SourceCandidate], list[str], bool]:
    """Select sources by priority while recording skipped sources and budget limits."""
    selected: list[SourceCandidate] = []
    skipped: list[str] = []
    budget_exhausted = False
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (-item.priority, item.estimated_cost, item.relative_path),
    )
    for candidate in sorted_candidates:
        if len(selected) >= budget.max_sources:
            skipped.append(f"{candidate.relative_path}: budget_exhausted")
            budget_exhausted = True
            continue
        if candidate.source_type == "documentation" and _count_docs(selected) >= budget.max_doc_summaries:
            skipped.append(f"{candidate.relative_path}: documentation_budget_exhausted")
            budget_exhausted = True
            continue
        selected.append(candidate)
    return selected, skipped, budget_exhausted


def summarize_repository_file(
    file_path: str | Path,
    project_root: str | Path,
    cache_root: str | Path | None = None,
    *,
    source_type: str = "source_file",
) -> dict[str, Any]:
    """Summarize a repository-local file and reuse the cache when it is current."""
    root = _resolve_project_root(project_root)
    path = _resolve_inside_root(file_path, root)
    active_cache_root = Path(cache_root) if cache_root else get_analysis_cache_dir(root)
    summary_dir = active_cache_root / "files"
    summary_dir.mkdir(parents=True, exist_ok=True)
    relative_path = _to_posix_relative(path, root)
    file_key = _safe_file_key(relative_path)
    summary_path = summary_dir / f"{file_key}.summary.md"
    meta_path = summary_dir / f"{file_key}.meta.json"
    stat = path.stat()
    metadata = {
        "version": 1,
        "relative_path": relative_path,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "source_type": source_type,
        "summary_path": str(summary_path),
    }
    if _cache_is_current(meta_path, metadata):
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload

    text, chars_read, limited = _read_text_sample(path)
    summary_text = _summarize_text(relative_path, text, source_type, limited=limited)
    summary_path.write_text(summary_text, encoding="utf-8")
    payload = {
        **metadata,
        "category": _documentation_category(relative_path),
        "title": _extract_title(relative_path, text),
        "summary": _first_sentence(summary_text),
        "user_visible": _is_user_visible_document(relative_path),
        "requires_sync_after_code_change": _is_user_visible_document(relative_path),
        "chars_read": chars_read,
        "cache_hit": False,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _documentation_candidates(root: Path, budget: AnalysisBudget) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    for relative in DOCUMENTATION_PATHS:
        path = root / relative
        if path.exists() and _is_safe_text_path(path):
            priority = 95 if relative in {"AGENTS.md", "README.md"} else 55
            candidates.append(_source_candidate(root, path, "documentation", priority, "repository documentation"))
    releases = sorted(root.glob("RELEASE_v*.md"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for path in releases[: budget.max_release_files]:
        if path.is_file() and _is_safe_text_path(path):
            candidates.append(_source_candidate(root, path, "documentation", 55, "recent release notes"))
    return candidates


def _explicit_path_candidates(root: Path, hints: AnalysisHints) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    for raw_path in hints.explicit_paths:
        try:
            path = _resolve_inside_root(root / raw_path, root)
        except ValueError:
            continue
        if ANALYSIS_CACHE_DIR_NAME in path.relative_to(root).parts:
            continue
        if path.exists() and path.is_file() and _is_safe_text_path(path):
            candidates.append(_source_candidate(root, path, "explicit_path", 100, "explicit user hint"))
    return candidates


def _core_source_candidates(root: Path) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    for relative in CORE_SOURCE_PATHS:
        path = root / relative
        if path.exists() and _is_safe_text_path(path):
            candidates.append(_source_candidate(root, path, "source_file", 75, "core tool entry"))
    return candidates


def _glob_candidates(root: Path, pattern: str, source_type: str, priority: int) -> list[SourceCandidate]:
    return [
        _source_candidate(root, path, source_type, priority, f"{source_type} pattern")
        for path in sorted(root.glob(pattern))
        if path.is_file() and _is_safe_text_path(path)
    ]


def _git_status_candidates(root: Path) -> list[SourceCandidate]:
    # Git output is converted into a cache file so the rest of the pipeline only
    # needs to process repository-local paths.
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if not result.stdout.strip():
        return []
    status_path = root / ANALYSIS_CACHE_DIR_NAME / "git-status.txt"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(result.stdout, encoding="utf-8")
    return [_source_candidate(root, status_path, "git_status", 80, "dirty worktree status")]


def _source_candidate(
    root: Path,
    path: Path,
    source_type: str,
    priority: int,
    reason: str,
) -> SourceCandidate:
    relative_path = _to_posix_relative(path, root)
    return SourceCandidate(
        relative_path=relative_path,
        source_type=source_type,
        priority=priority,
        reason=reason,
        estimated_cost=min(path.stat().st_size, DEFAULT_MAX_TEXT_FILE_BYTES),
    )


def _deduplicate_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    by_path: dict[str, SourceCandidate] = {}
    for candidate in candidates:
        current = by_path.get(candidate.relative_path)
        if current is None or candidate.priority > current.priority:
            by_path[candidate.relative_path] = candidate
    return list(by_path.values())


def _documentation_summary_from_payload(payload: dict[str, Any]) -> DocumentationSummary:
    return DocumentationSummary(
        relative_path=str(payload["relative_path"]),
        category=str(payload.get("category") or "other"),
        title=str(payload.get("title") or payload["relative_path"]),
        summary=str(payload.get("summary") or ""),
        user_visible=bool(payload.get("user_visible", False)),
        requires_sync_after_code_change=bool(payload.get("requires_sync_after_code_change", False)),
        size=int(payload.get("size") or 0),
        mtime_ns=int(payload.get("mtime_ns") or 0),
        cache_hit=bool(payload.get("cache_hit", False)),
        summary_path=str(payload.get("summary_path") or ""),
    )


def _suggest_documentation_updates(
    hints: AnalysisHints,
    docs: list[DocumentationSummary],
) -> list[str]:
    if not hints.require_documentation_sync_check:
        return []
    requirement = hints.requirement.lower()
    user_visible_terms = ("config", "tool", "schema", "command", "readme", "user", "release", "workflow")
    if not any(term in requirement for term in user_visible_terms):
        return []
    return [doc.relative_path for doc in docs if doc.requires_sync_after_code_change]


def _format_task_context_summary(
    *,
    purpose: str,
    selected_sources: list[SelectedSource],
    documentation_updates: list[str],
    skipped_sources: list[str],
) -> str:
    lines = [
        "# Task Context Summary",
        "",
        f"- Purpose: {purpose}",
        f"- Selected sources: {len(selected_sources)}",
        f"- Cache hits: {sum(1 for source in selected_sources if source.cache_hit)}",
        "",
        "## Selected Sources",
        "",
    ]
    lines.extend(f"- {source.relative_path}: {source.reason}" for source in selected_sources)
    lines.extend(["", "## Documentation Sync Candidates", ""])
    if documentation_updates:
        lines.extend(f"- {path}" for path in documentation_updates)
    else:
        lines.append("- None identified.")
    lines.extend(["", "## Skipped Sources", ""])
    lines.extend(f"- {source}" for source in skipped_sources) if skipped_sources else lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def _write_cache_index(cache_root: Path, context: AnalysisContext) -> None:
    index_path = cache_root / "index.json"
    payload = {
        "version": 1,
        "last_context_run_id": context.context_run_id,
        "last_context_state_path": context.context_state_path,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _summarize_text(relative_path: str, text: str, source_type: str, *, limited: bool) -> str:
    headings = _markdown_headings(text)
    symbols = _python_symbols(text) if relative_path.endswith(".py") else []
    top_level_keys = _top_level_keys(text) if relative_path.endswith((".json", ".toml", ".yaml", ".yml")) else []
    lines = [
        f"# Summary: {relative_path}",
        "",
        f"- Source type: {source_type}",
        f"- Summary limited: {str(limited).lower()}",
    ]
    if headings:
        lines.append(f"- Headings: {', '.join(headings[:8])}")
    if symbols:
        lines.append(f"- Python symbols: {', '.join(symbols[:20])}")
    if top_level_keys:
        lines.append(f"- Top-level keys: {', '.join(top_level_keys[:20])}")
    if not headings and not symbols and not top_level_keys:
        lines.append(f"- Text preview: {_single_line(text[:240])}")
    lines.append("")
    return "\n".join(lines)


def _read_text_sample(path: Path) -> tuple[str, int, bool]:
    raw = path.read_bytes()[:DEFAULT_MAX_TEXT_FILE_BYTES]
    text = raw.decode("utf-8", errors="replace")
    limited = path.stat().st_size > len(raw)
    return text, len(text), limited


def _markdown_headings(text: str) -> list[str]:
    return [
        match.group(1).strip()
        for line in text.splitlines()
        if (match := re.match(r"^\s{0,3}#{1,3}\s+(.+)$", line))
    ]


def _python_symbols(text: str) -> list[str]:
    pattern = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
    return pattern.findall(text)


def _top_level_keys(text: str) -> list[str]:
    keys: list[str] = []
    for line in text.splitlines():
        if match := re.match(r"^([A-Za-z0-9_.-]+)\s*[:=]", line):
            key = match.group(1)
            if not _looks_sensitive(key):
                keys.append(key)
    return keys


def _extract_title(relative_path: str, text: str) -> str:
    headings = _markdown_headings(text)
    return headings[0] if headings else relative_path


def _first_sentence(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip(" -")
        if clean and not clean.startswith("#"):
            return clean[:240]
    return ""


def _single_line(text: str) -> str:
    return " ".join(text.split())


def _documentation_category(relative_path: str) -> str:
    if relative_path == "AGENTS.md":
        return "agent_instructions"
    if relative_path == "README.md":
        return "project_overview"
    if relative_path.startswith("RELEASE_"):
        return "release_notes"
    if relative_path in {"pyproject.toml", "requirements.txt", "package.json"}:
        return "project_metadata"
    return "documentation"


def _is_user_visible_document(relative_path: str) -> bool:
    return relative_path.endswith(".md") or relative_path in {"pyproject.toml", "package.json"}


def _count_docs(candidates: list[SourceCandidate]) -> int:
    return sum(1 for candidate in candidates if candidate.source_type == "documentation")


def _cache_is_current(meta_path: Path, metadata: dict[str, Any]) -> bool:
    if not meta_path.exists():
        return False
    try:
        current = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return all(current.get(key) == value for key, value in metadata.items() if key != "summary_path")


def _safe_file_key(relative_path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", relative_path).strip("-").lower() or "root"


def _resolve_project_root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"project_root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"project_root must be a directory: {root}")
    return root


def _resolve_inside_root(path: str | Path, root: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path is outside project_root: {resolved}")
    if not _is_safe_text_path(resolved):
        raise ValueError(f"path is not a safe text source: {resolved}")
    return resolved


def _to_posix_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _is_safe_text_path(path: Path) -> bool:
    parts = set(path.parts)
    blocked_dirs = {".git", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build"}
    if parts & blocked_dirs:
        return False
    name = path.name.lower()
    blocked_suffixes = (".pem", ".key", ".p12", ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip")
    if name == ".env" or name.startswith(".env.") or name.endswith(blocked_suffixes):
        return False
    return not any(term in name for term in ("secret", "token", "credential"))


def _looks_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(term in lowered for term in ("secret", "token", "password", "credential", "api_key"))


def _default_budget_for_purpose(purpose: str) -> AnalysisBudget:
    if purpose == "approval":
        return DEFAULT_APPROVAL_BUDGET
    return DEFAULT_THINKING_BUDGET
