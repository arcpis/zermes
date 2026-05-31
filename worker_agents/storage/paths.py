"""Canonical worker-agent storage roots."""

from pathlib import Path

from hermes_constants import get_hermes_home


WORKER_AGENTS_DIR_NAME = "worker_agents"
ORGANIZATION_DIR_NAME = "organization"
ORGANIZATION_ACTIVE_FILE_NAME = "active.json"
ORGANIZATION_PROPOSALS_DIR_NAME = "proposals"
ORGANIZATION_HISTORY_DIR_NAME = "history"


def _install_root() -> Path:
    """Return the application install root for this source layout."""
    return Path(__file__).resolve().parents[2]


def get_worker_agents_home() -> Path:
    """Return durable worker-agent storage under the active profile home."""
    return get_hermes_home() / WORKER_AGENTS_DIR_NAME


def get_worker_agents_organization_dir() -> Path:
    """Return durable organization storage under the active profile home."""
    return get_worker_agents_home() / ORGANIZATION_DIR_NAME


def get_active_organization_path() -> Path:
    """Return the active organization tree file path without creating it."""
    return get_worker_agents_organization_dir() / ORGANIZATION_ACTIVE_FILE_NAME


def get_organization_proposals_dir() -> Path:
    """Return the durable organization proposal summary directory."""
    return get_worker_agents_organization_dir() / ORGANIZATION_PROPOSALS_DIR_NAME


def get_organization_history_dir() -> Path:
    """Return the durable organization history summary directory."""
    return get_worker_agents_organization_dir() / ORGANIZATION_HISTORY_DIR_NAME


def get_worker_agents_data_dir(install_root: Path | None = None) -> Path:
    """Return clearable worker-agent runtime storage under install ``data/``."""
    root = _install_root() if install_root is None else Path(install_root)
    return root / "data" / WORKER_AGENTS_DIR_NAME


def get_worker_agents_runtime_organization_dir(install_root: Path | None = None) -> Path:
    """Return clearable runtime organization storage under install ``data/``."""
    return get_worker_agents_data_dir(install_root=install_root) / ORGANIZATION_DIR_NAME


def ensure_worker_agents_home() -> Path:
    """Create and return the durable worker-agent storage root."""
    path = get_worker_agents_home()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_worker_agents_organization_dir() -> Path:
    """Create durable organization directories without creating organization data."""
    root = get_worker_agents_organization_dir()
    get_organization_proposals_dir().mkdir(parents=True, exist_ok=True)
    get_organization_history_dir().mkdir(parents=True, exist_ok=True)
    return root


def ensure_worker_agents_data_dir(install_root: Path | None = None) -> Path:
    """Create and return the clearable worker-agent runtime storage root."""
    path = get_worker_agents_data_dir(install_root=install_root)
    path.mkdir(parents=True, exist_ok=True)
    return path
