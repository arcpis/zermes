"""Durable organization storage for active managed-worker structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from utils import atomic_json_write

from ..organization import (
    OrgTree,
    OrganizationError,
    load_org_tree_json,
    org_tree_from_dict,
    org_tree_to_dict,
)
from .paths import (
    get_active_organization_path,
    get_organization_history_dir,
    get_organization_proposals_dir,
    get_worker_agents_organization_dir,
)


@dataclass
class OrganizationStore:
    """Profile-home storage for durable organization records."""

    root: Path = field(default_factory=get_worker_agents_organization_dir)

    @property
    def active_path(self) -> Path:
        return self.root / "active.json"

    @property
    def proposals_dir(self) -> Path:
        return self.root / "proposals"

    @property
    def history_dir(self) -> Path:
        return self.root / "history"

    def initialize(self) -> Path:
        """Create organization directories without creating organization data."""
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        return self.root

    def load_active_organization(self) -> OrgTree | None:
        """Load the active organization tree, returning ``None`` when absent."""
        if not self.active_path.exists():
            return None
        return load_org_tree_json(self.active_path.read_text(encoding="utf-8"))

    def save_active_organization(
        self, tree: OrgTree, *, expected_revision: int | None = None
    ) -> Path:
        """Atomically save the active tree after validating revision expectations."""
        current_tree = self.load_active_organization()
        current_revision = current_tree.revision if current_tree is not None else None
        if expected_revision is not None and current_revision != expected_revision:
            raise OrganizationError(
                "active organization revision conflict: "
                f"expected {expected_revision!r}, found {current_revision!r}"
            )
        if expected_revision is not None and tree.revision <= expected_revision:
            raise OrganizationError("active organization revision must advance")

        data = org_tree_to_dict(tree)
        org_tree_from_dict(data)
        self.initialize()
        atomic_json_write(self.active_path, data)
        return self.active_path


def get_default_organization_store() -> OrganizationStore:
    """Return an organization store rooted at the active profile home."""
    return OrganizationStore(root=get_worker_agents_organization_dir())


def get_default_active_organization_path() -> Path:
    """Return the active organization file path for callers that only need a path."""
    return get_active_organization_path()


def get_default_organization_proposals_dir() -> Path:
    """Return the default proposal summary directory."""
    return get_organization_proposals_dir()


def get_default_organization_history_dir() -> Path:
    """Return the default history summary directory."""
    return get_organization_history_dir()
