"""Read-only helpers for root Worker Agent discovery.

The prompt path and the CLI product path both need the same low-sensitivity
view of top-level workers.  Keeping it here avoids importing CLI modules from
agent prompt construction, which must also run in gateway and embedded contexts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from hermes_constants import get_hermes_home


MANAGEMENT_STATE_RELATIVE_PATH = Path("worker_agents") / "management" / "dashboard_state.json"
DEFAULT_GROUP_THREAD_ID = "thread-default-group"
FORBIDDEN_MANAGEMENT_KEY_MARKERS = (
    "api_key",
    "credential",
    "password",
    "raw_transcript",
    "secret",
    "stderr",
    "stdout",
    "token",
    "transcript",
)


def load_worker_management_state(home: Path | None = None) -> dict[str, Any]:
    """Load sanitized Worker Agents management state from the active profile."""

    state_path = worker_management_state_path(home)
    if not state_path.exists():
        return empty_worker_management_state()
    with state_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError("Worker Agents management state must be a JSON object")
    return sanitize_worker_management_mapping(data)


def worker_management_state_path(home: Path | None = None) -> Path:
    """Return the profile-scoped management state path."""

    return (home or get_hermes_home()) / MANAGEMENT_STATE_RELATIVE_PATH


def collect_enabled_root_worker_ids(state: Mapping[str, Any]) -> list[str]:
    """Return enabled workers represented directly under the organization root."""

    organization_tree = _optional_mapping(state.get("organization_tree"))
    if organization_tree is None:
        return []
    nodes = _mapping(organization_tree.get("nodes"))
    root_node_id = str(organization_tree.get("root_node_id", "root"))
    root_node = _optional_mapping(nodes.get(root_node_id))
    if root_node is None:
        return []

    worker_records = _mapping(state.get("worker_records"))
    collected: list[str] = []

    for worker_id in _list_value(root_node.get("member_worker_ids")):
        if isinstance(worker_id, str) and worker_id and _worker_is_enabled(worker_records.get(worker_id)):
            collected.append(worker_id)

    for child_id in _list_value(root_node.get("child_ids")):
        if not isinstance(child_id, str):
            continue
        child = _optional_mapping(nodes.get(child_id))
        if child is None:
            continue
        for worker_id in _department_worker_ids(child, nodes):
            if _worker_is_enabled(worker_records.get(worker_id)):
                collected.append(worker_id)

    return list(dict.fromkeys(collected))


def empty_worker_management_state() -> dict[str, Any]:
    """Return the stable empty shape used by Worker Agents product views."""

    return {
        "worker_records": {},
        "organization_tree": None,
        "department_summaries": [],
        "threads": [],
        "mentions": [],
        "broadcasts": [],
        "approvals": [],
        "assets": [],
        "evolution": [],
        "retention_candidates": [],
    }


def sanitize_worker_management_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Drop sensitive-looking fields from the low-sensitivity management state."""

    result: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if _is_forbidden_key(key_text):
            continue
        result[key_text] = _sanitize_value(value)
    return result


def _department_worker_ids(
    node: Mapping[str, Any],
    nodes: Mapping[str, Any],
) -> list[str]:
    result: list[str] = []
    leader = _optional_mapping(node.get("leader"))
    if leader is not None and leader.get("kind") == "worker":
        worker_id = leader.get("worker_id")
        if isinstance(worker_id, str) and worker_id:
            result.append(worker_id)

    for worker_id in _list_value(node.get("member_worker_ids")):
        if isinstance(worker_id, str) and worker_id:
            result.append(worker_id)

    # A root child contributes its direct child leads/individuals to the default
    # group; deeper members remain scoped to their own department chat.
    for child_id in _list_value(node.get("child_ids")):
        if not isinstance(child_id, str):
            continue
        child = _optional_mapping(nodes.get(child_id))
        if child is None:
            continue
        child_worker_id = _direct_child_worker_id(child)
        if child_worker_id:
            result.append(child_worker_id)

    return list(dict.fromkeys(result))


def _direct_child_worker_id(node: Mapping[str, Any]) -> str | None:
    if str(node.get("node_type", "")).lower() == "individual":
        worker_id = node.get("individual_worker_id")
        return worker_id if isinstance(worker_id, str) and worker_id else None

    leader = _optional_mapping(node.get("leader"))
    if leader is None or leader.get("kind") != "worker":
        return None
    worker_id = leader.get("worker_id")
    return worker_id if isinstance(worker_id, str) and worker_id else None


def _worker_is_enabled(worker: Any) -> bool:
    record = _optional_mapping(worker)
    return record is not None and str(record.get("status", "")).lower() == "enabled"


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return sanitize_worker_management_mapping(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return "[redacted summary]" if _is_forbidden_text(value) else value
    return value


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in FORBIDDEN_MANAGEMENT_KEY_MARKERS)


def _is_forbidden_text(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in FORBIDDEN_MANAGEMENT_KEY_MARKERS)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []
