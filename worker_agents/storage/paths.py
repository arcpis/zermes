"""Canonical worker-agent storage roots."""

from pathlib import Path

from hermes_constants import get_hermes_home


WORKER_AGENTS_DIR_NAME = "worker_agents"


def _install_root() -> Path:
    """Return the application install root for this source layout."""
    return Path(__file__).resolve().parents[2]


def get_worker_agents_home() -> Path:
    """Return durable worker-agent storage under the active profile home."""
    return get_hermes_home() / WORKER_AGENTS_DIR_NAME


def get_worker_agents_data_dir(install_root: Path | None = None) -> Path:
    """Return clearable worker-agent runtime storage under install ``data/``."""
    root = _install_root() if install_root is None else Path(install_root)
    return root / "data" / WORKER_AGENTS_DIR_NAME


def ensure_worker_agents_home() -> Path:
    """Create and return the durable worker-agent storage root."""
    path = get_worker_agents_home()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_worker_agents_data_dir(install_root: Path | None = None) -> Path:
    """Create and return the clearable worker-agent runtime storage root."""
    path = get_worker_agents_data_dir(install_root=install_root)
    path.mkdir(parents=True, exist_ok=True)
    return path
