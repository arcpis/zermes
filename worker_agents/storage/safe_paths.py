"""Small path guards shared by worker-agent stores."""

from pathlib import Path


def ensure_single_segment_dir(parent: Path, name: str) -> Path:
    """Create a child directory when ``name`` is exactly one path segment."""
    if not name or Path(name).name != name:
        raise ValueError(f"Expected a single path segment, got {name!r}")
    path = parent / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_under_root(root: Path, relative_path: str | Path) -> Path:
    """Resolve a relative path and reject attempts to escape ``root``."""
    candidate = root / relative_path
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if (
        resolved_candidate != resolved_root
        and resolved_root not in resolved_candidate.parents
    ):
        raise ValueError(f"Path escapes worker-agent storage root: {relative_path!r}")
    return candidate
