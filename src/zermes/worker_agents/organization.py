"""Durable organization contract for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping

from .profile import WorkerProfileError, validate_worker_id
from .registry import WorkerLifecycleStatus


ORGANIZATION_SCHEMA_VERSION = 1
MAIN_AGENT_ID = "zermes_main_agent"
AVAILABLE_ORGANIZATION_WORKER_STATUSES = frozenset(
    {
        WorkerLifecycleStatus.REGISTERED.value,
        WorkerLifecycleStatus.ENABLED.value,
        WorkerLifecycleStatus.DISABLED.value,
    }
)


class OrganizationError(ValueError):
    """Raised when an organization contract is invalid."""


class OrgNodeType(StrEnum):
    """Kinds of nodes allowed in the durable organization tree."""

    ROOT = "root"
    DEPARTMENT = "department"
    TEAM = "team"
    INDIVIDUAL = "individual"


class OrgLeaderKind(StrEnum):
    """Supported leader reference targets."""

    MAIN_AGENT = "main_agent"
    WORKER = "worker"
    NONE = "none"


class OrgLifecycleState(StrEnum):
    """Organization node lifecycle used by active and historical trees."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise OrganizationError(f"{field_name} must be a string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OrganizationError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise OrganizationError(f"{field_name} must be a list of non-empty strings")
    return result


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OrganizationError(f"{field_name} must be a non-negative integer")
    return value


def _bool_value(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise OrganizationError(f"{field_name} must be a boolean")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise OrganizationError(f"{field_name} has unknown fields: {joined}")


def validate_org_node_id(org_node_id: str) -> str:
    """Return a stable organization node id after rejecting path-like values."""
    if not org_node_id or org_node_id in {".", ".."}:
        raise OrganizationError("org_node_id must be a non-empty path segment")
    if "/" in org_node_id or "\\" in org_node_id:
        raise OrganizationError("org_node_id must not contain path separators")
    return org_node_id


def _coerce_node_type(value: OrgNodeType | str) -> OrgNodeType:
    if isinstance(value, OrgNodeType):
        return value
    raw_type = _require_string(value, "node_type")
    try:
        return OrgNodeType(raw_type)
    except ValueError as exc:
        raise OrganizationError(f"Unknown organization node type: {raw_type!r}") from exc


def _coerce_leader_kind(value: OrgLeaderKind | str) -> OrgLeaderKind:
    if isinstance(value, OrgLeaderKind):
        return value
    raw_kind = _require_string(value, "leader.kind")
    try:
        return OrgLeaderKind(raw_kind)
    except ValueError as exc:
        raise OrganizationError(f"Unknown organization leader kind: {raw_kind!r}") from exc


def _coerce_lifecycle(value: OrgLifecycleState | str) -> OrgLifecycleState:
    if isinstance(value, OrgLifecycleState):
        return value
    raw_state = _require_string(value, "lifecycle")
    try:
        return OrgLifecycleState(raw_state)
    except ValueError as exc:
        raise OrganizationError(f"Unknown organization lifecycle: {raw_state!r}") from exc


def _validate_worker_id_as_org_error(worker_id: str, field_name: str) -> str:
    try:
        return validate_worker_id(worker_id)
    except WorkerProfileError as exc:
        raise OrganizationError(f"{field_name} is invalid: {exc}") from exc


@dataclass(frozen=True)
class OrgLeaderRef:
    """Low-sensitivity reference to the owner of an organization node."""

    kind: OrgLeaderKind = OrgLeaderKind.NONE
    worker_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_leader_kind(self.kind))
        if self.kind == OrgLeaderKind.WORKER:
            if self.worker_id is None:
                raise OrganizationError("leader.worker_id is required for worker leaders")
            _validate_worker_id_as_org_error(self.worker_id, "leader.worker_id")
        elif self.worker_id is not None:
            raise OrganizationError("leader.worker_id is only valid for worker leaders")


@dataclass(frozen=True)
class OrgChatPolicy:
    """Default chat policy reference without creating or binding a thread."""

    default_thread_policy: str = "none"
    allow_default_group_chat: bool = False


@dataclass(frozen=True)
class OrgNode:
    """Durable organization node that references workers without owning them."""

    org_node_id: str
    name: str
    node_type: OrgNodeType
    description: str = ""
    responsibilities: tuple[str, ...] = ()
    applicable_task_types: tuple[str, ...] = ()
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    leader: OrgLeaderRef = field(default_factory=OrgLeaderRef)
    member_worker_ids: tuple[str, ...] = ()
    individual_worker_id: str | None = None
    chat_policy: OrgChatPolicy = field(default_factory=OrgChatPolicy)
    lifecycle: OrgLifecycleState = OrgLifecycleState.DRAFT
    schema_version: int = ORGANIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_org_node_id(self.org_node_id)
        object.__setattr__(self, "node_type", _coerce_node_type(self.node_type))
        object.__setattr__(self, "lifecycle", _coerce_lifecycle(self.lifecycle))
        _require_string(self.name, "name")
        if self.schema_version != ORGANIZATION_SCHEMA_VERSION:
            raise OrganizationError(
                f"Unsupported organization schema_version: {self.schema_version!r}"
            )
        if self.parent_id is not None:
            validate_org_node_id(self.parent_id)
        for child_id in self.child_ids:
            validate_org_node_id(child_id)
        for worker_id in self.member_worker_ids:
            _validate_worker_id_as_org_error(worker_id, "member_worker_ids")
        if self.individual_worker_id is not None:
            _validate_worker_id_as_org_error(
                self.individual_worker_id, "individual_worker_id"
            )
        if self.node_type == OrgNodeType.ROOT and self.parent_id is not None:
            raise OrganizationError("root nodes must not have a parent_id")
        if self.node_type == OrgNodeType.INDIVIDUAL and self.individual_worker_id is None:
            raise OrganizationError("individual nodes require individual_worker_id")
        if self.node_type != OrgNodeType.INDIVIDUAL and self.individual_worker_id is not None:
            raise OrganizationError(
                "individual_worker_id is only valid for individual nodes"
            )


@dataclass(frozen=True)
class OrgTree:
    """Durable organization tree snapshot with structural validation."""

    tree_id: str
    root_node_id: str
    nodes: Mapping[str, OrgNode]
    revision: int = 0
    schema_version: int = ORGANIZATION_SCHEMA_VERSION
    created_at: str | None = None
    updated_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_org_node_id(self.tree_id)
        validate_org_node_id(self.root_node_id)
        if self.schema_version != ORGANIZATION_SCHEMA_VERSION:
            raise OrganizationError(
                f"Unsupported organization schema_version: {self.schema_version!r}"
            )
        _non_negative_int(self.revision, "revision")
        normalized_nodes = dict(self.nodes)
        object.__setattr__(self, "nodes", normalized_nodes)
        validate_org_tree_structure(self)


@dataclass(frozen=True)
class OrgNodeSummary:
    """Low-sensitivity summary safe for chat context, audit, and UI lists."""

    org_node_id: str
    name: str
    node_type: OrgNodeType
    lifecycle: OrgLifecycleState
    parent_id: str | None
    child_count: int
    member_count: int
    leader_kind: OrgLeaderKind
    leader_worker_id: str | None = None
    responsibility_summary: str = ""
    applicable_task_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrgTreeSummary:
    """Low-sensitivity aggregate summary for one organization tree."""

    tree_id: str
    revision: int
    root_node_id: str
    active_node_count: int
    department_count: int
    team_count: int
    individual_count: int
    node_summaries: tuple[OrgNodeSummary, ...]


_LEADER_FIELDS = {"kind", "worker_id"}
_CHAT_POLICY_FIELDS = {"default_thread_policy", "allow_default_group_chat"}
_NODE_FIELDS = {
    "org_node_id",
    "schema_version",
    "name",
    "node_type",
    "description",
    "responsibilities",
    "applicable_task_types",
    "parent_id",
    "child_ids",
    "leader",
    "member_worker_ids",
    "individual_worker_id",
    "chat_policy",
    "lifecycle",
}
_TREE_FIELDS = {
    "tree_id",
    "schema_version",
    "revision",
    "root_node_id",
    "nodes",
    "created_at",
    "updated_at",
    "metadata",
}


def org_leader_ref_from_dict(data: Mapping[str, Any] | None) -> OrgLeaderRef:
    if data is None:
        return OrgLeaderRef()
    data = _require_mapping(data, "leader")
    _reject_unknown_fields(data, _LEADER_FIELDS, "leader")
    return OrgLeaderRef(
        kind=_coerce_leader_kind(data.get("kind", OrgLeaderKind.NONE.value)),
        worker_id=_optional_string(data.get("worker_id"), "leader.worker_id"),
    )


def org_leader_ref_to_dict(leader: OrgLeaderRef) -> dict[str, Any]:
    return {
        "kind": leader.kind.value,
        "worker_id": leader.worker_id,
    }


def org_chat_policy_from_dict(data: Mapping[str, Any] | None) -> OrgChatPolicy:
    if data is None:
        return OrgChatPolicy()
    data = _require_mapping(data, "chat_policy")
    _reject_unknown_fields(data, _CHAT_POLICY_FIELDS, "chat_policy")
    return OrgChatPolicy(
        default_thread_policy=_require_string(
            data.get("default_thread_policy", "none"),
            "chat_policy.default_thread_policy",
        ),
        allow_default_group_chat=_bool_value(
            data.get("allow_default_group_chat", False),
            "chat_policy.allow_default_group_chat",
        ),
    )


def org_chat_policy_to_dict(chat_policy: OrgChatPolicy) -> dict[str, Any]:
    return {
        "default_thread_policy": chat_policy.default_thread_policy,
        "allow_default_group_chat": chat_policy.allow_default_group_chat,
    }


def org_node_from_dict(data: Mapping[str, Any]) -> OrgNode:
    data = _require_mapping(data, "org_node")
    _reject_unknown_fields(data, _NODE_FIELDS, "org_node")
    return OrgNode(
        org_node_id=_require_string(data.get("org_node_id"), "org_node_id"),
        schema_version=data.get("schema_version", ORGANIZATION_SCHEMA_VERSION),
        name=_require_string(data.get("name"), "name"),
        node_type=_coerce_node_type(data.get("node_type")),
        description=_string_value(data.get("description", ""), "description"),
        responsibilities=_string_tuple(
            data.get("responsibilities", ()), "responsibilities"
        ),
        applicable_task_types=_string_tuple(
            data.get("applicable_task_types", ()), "applicable_task_types"
        ),
        parent_id=_optional_string(data.get("parent_id"), "parent_id"),
        child_ids=_string_tuple(data.get("child_ids", ()), "child_ids"),
        leader=org_leader_ref_from_dict(data.get("leader")),
        member_worker_ids=_string_tuple(
            data.get("member_worker_ids", ()), "member_worker_ids"
        ),
        individual_worker_id=_optional_string(
            data.get("individual_worker_id"), "individual_worker_id"
        ),
        chat_policy=org_chat_policy_from_dict(data.get("chat_policy")),
        lifecycle=_coerce_lifecycle(data.get("lifecycle", OrgLifecycleState.DRAFT.value)),
    )


def org_node_to_dict(node: OrgNode) -> dict[str, Any]:
    return {
        "org_node_id": node.org_node_id,
        "schema_version": node.schema_version,
        "name": node.name,
        "node_type": node.node_type.value,
        "description": node.description,
        "responsibilities": list(node.responsibilities),
        "applicable_task_types": list(node.applicable_task_types),
        "parent_id": node.parent_id,
        "child_ids": list(node.child_ids),
        "leader": org_leader_ref_to_dict(node.leader),
        "member_worker_ids": list(node.member_worker_ids),
        "individual_worker_id": node.individual_worker_id,
        "chat_policy": org_chat_policy_to_dict(node.chat_policy),
        "lifecycle": node.lifecycle.value,
    }


def validate_org_tree_structure(tree: OrgTree) -> None:
    """Validate parent/child links and lifecycle-safe active tree targets."""
    if not tree.nodes:
        raise OrganizationError("organization tree must contain at least one node")
    if tree.root_node_id not in tree.nodes:
        raise OrganizationError("root_node_id must reference an existing node")

    root_nodes = [
        node for node in tree.nodes.values() if node.node_type == OrgNodeType.ROOT
    ]
    if len(root_nodes) != 1:
        raise OrganizationError("organization tree must contain exactly one root node")
    root_node = root_nodes[0]
    if root_node.org_node_id != tree.root_node_id:
        raise OrganizationError("root_node_id must match the root node")

    for node_id, node in tree.nodes.items():
        if node_id != node.org_node_id:
            raise OrganizationError("nodes mapping key must match org_node_id")
        if node.node_type != OrgNodeType.ROOT and node.parent_id is None:
            raise OrganizationError(f"node {node.org_node_id!r} must have a parent_id")
        if node.parent_id is not None and node.parent_id not in tree.nodes:
            raise OrganizationError(
                f"node {node.org_node_id!r} references missing parent_id"
            )
        if node.lifecycle == OrgLifecycleState.ARCHIVED and node.chat_policy.allow_default_group_chat:
            raise OrganizationError("archived nodes cannot be default chat targets")
        for child_id in node.child_ids:
            if child_id not in tree.nodes:
                raise OrganizationError(
                    f"node {node.org_node_id!r} references missing child_id"
                )
            child = tree.nodes[child_id]
            if child.parent_id != node.org_node_id:
                raise OrganizationError(
                    f"child node {child_id!r} does not point back to its parent"
                )

    child_ids = {
        child_id for node in tree.nodes.values() for child_id in node.child_ids
    }
    expected_child_ids = {
        node.org_node_id for node in tree.nodes.values() if node.parent_id is not None
    }
    if child_ids != expected_child_ids:
        raise OrganizationError("parent child_ids must match child parent_id values")

    for parent in tree.nodes.values():
        sibling_names: set[str] = set()
        for child_id in parent.child_ids:
            child_name = tree.nodes[child_id].name
            if child_name in sibling_names:
                raise OrganizationError(
                    f"children of {parent.org_node_id!r} must have unique names"
                )
            sibling_names.add(child_name)

    _validate_tree_has_no_cycles(tree)


def validate_org_tree_references(
    tree: OrgTree,
    worker_lookup: Mapping[str, Any] | set[str] | Callable[[str], Any],
) -> None:
    """Validate that organization worker references point to existing workers.

    The lookup is deliberately read-only and tiny: callers may pass a set of
    worker ids, a mapping of worker id to status/record, or a callable returning
    either. This keeps the organization contract independent from profile and
    registry stores.
    """
    for node in tree.nodes.values():
        _validate_leader_reference(node, worker_lookup)
        for worker_id in node.member_worker_ids:
            _require_available_worker(worker_id, worker_lookup, "member_worker_ids")
        if node.individual_worker_id is not None:
            _require_available_worker(
                node.individual_worker_id, worker_lookup, "individual_worker_id"
            )
    _validate_sibling_individual_worker_uniqueness(tree)


def _validate_leader_reference(
    node: OrgNode, worker_lookup: Mapping[str, Any] | set[str] | Callable[[str], Any]
) -> None:
    if node.leader.kind == OrgLeaderKind.MAIN_AGENT:
        return
    if node.leader.kind == OrgLeaderKind.NONE:
        return
    if node.leader.worker_id is None:
        raise OrganizationError(f"node {node.org_node_id!r} has missing leader worker_id")
    _require_available_worker(node.leader.worker_id, worker_lookup, "leader.worker_id")


def _validate_sibling_individual_worker_uniqueness(tree: OrgTree) -> None:
    for parent in tree.nodes.values():
        seen_worker_ids: set[str] = set()
        for child_id in parent.child_ids:
            child = tree.nodes[child_id]
            if child.individual_worker_id is None:
                continue
            if child.individual_worker_id in seen_worker_ids:
                raise OrganizationError(
                    f"worker {child.individual_worker_id!r} appears more than once "
                    f"under parent {parent.org_node_id!r}"
                )
            seen_worker_ids.add(child.individual_worker_id)


def _require_available_worker(
    worker_id: str,
    worker_lookup: Mapping[str, Any] | set[str] | Callable[[str], Any],
    field_name: str,
) -> None:
    worker_record = _lookup_worker(worker_id, worker_lookup)
    if worker_record is None or worker_record is False:
        raise OrganizationError(f"{field_name} references missing worker {worker_id!r}")
    status = _worker_status_value(worker_record)
    if status is not None and status not in AVAILABLE_ORGANIZATION_WORKER_STATUSES:
        raise OrganizationError(
            f"{field_name} references unavailable worker {worker_id!r}: {status!r}"
        )


def _lookup_worker(
    worker_id: str, worker_lookup: Mapping[str, Any] | set[str] | Callable[[str], Any]
) -> Any:
    if callable(worker_lookup):
        return worker_lookup(worker_id)
    if isinstance(worker_lookup, set):
        return True if worker_id in worker_lookup else None
    return worker_lookup.get(worker_id)


def _worker_status_value(worker_record: Any) -> str | None:
    if isinstance(worker_record, WorkerLifecycleStatus):
        return worker_record.value
    if isinstance(worker_record, str):
        if worker_record == "":
            return None
        return worker_record
    status = getattr(worker_record, "status", None)
    if isinstance(status, WorkerLifecycleStatus):
        return status.value
    if isinstance(status, str):
        return status
    if isinstance(worker_record, Mapping):
        raw_status = worker_record.get("status")
        if isinstance(raw_status, WorkerLifecycleStatus):
            return raw_status.value
        if isinstance(raw_status, str):
            return raw_status
    return None


def _validate_tree_has_no_cycles(tree: OrgTree) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise OrganizationError("organization tree must not contain cycles")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child_id in tree.nodes[node_id].child_ids:
            visit(child_id)
        visiting.remove(node_id)
        visited.add(node_id)

    visit(tree.root_node_id)
    if visited != set(tree.nodes):
        raise OrganizationError("organization tree contains nodes unreachable from root")


def org_tree_from_dict(data: Mapping[str, Any]) -> OrgTree:
    data = _require_mapping(data, "org_tree")
    _reject_unknown_fields(data, _TREE_FIELDS, "org_tree")
    raw_nodes = _require_mapping(data.get("nodes"), "nodes")
    nodes = {
        _require_string(node_id, "nodes key"): org_node_from_dict(
            _require_mapping(node_data, f"nodes.{node_id}")
        )
        for node_id, node_data in raw_nodes.items()
    }
    return OrgTree(
        tree_id=_require_string(data.get("tree_id"), "tree_id"),
        schema_version=data.get("schema_version", ORGANIZATION_SCHEMA_VERSION),
        revision=_non_negative_int(data.get("revision", 0), "revision"),
        root_node_id=_require_string(data.get("root_node_id"), "root_node_id"),
        nodes=nodes,
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        metadata=dict(_require_mapping(data.get("metadata", {}), "metadata")),
    )


def org_tree_to_dict(tree: OrgTree) -> dict[str, Any]:
    return {
        "tree_id": tree.tree_id,
        "schema_version": tree.schema_version,
        "revision": tree.revision,
        "root_node_id": tree.root_node_id,
        "nodes": {
            node_id: org_node_to_dict(node)
            for node_id, node in sorted(tree.nodes.items())
        },
        "created_at": tree.created_at,
        "updated_at": tree.updated_at,
        "metadata": dict(tree.metadata),
    }


def summarize_org_node(node: OrgNode) -> OrgNodeSummary:
    """Return a low-sensitivity summary for one organization node."""
    return OrgNodeSummary(
        org_node_id=node.org_node_id,
        name=node.name,
        node_type=node.node_type,
        lifecycle=node.lifecycle,
        parent_id=node.parent_id,
        child_count=len(node.child_ids),
        member_count=len(node.member_worker_ids)
        + (1 if node.individual_worker_id is not None else 0),
        leader_kind=node.leader.kind,
        leader_worker_id=node.leader.worker_id,
        responsibility_summary=node.description,
        applicable_task_types=node.applicable_task_types,
    )


def summarize_org_tree(tree: OrgTree) -> OrgTreeSummary:
    """Return a low-sensitivity aggregate summary for an organization tree."""
    validate_org_tree_structure(tree)
    node_summaries = tuple(
        summarize_org_node(node) for _, node in sorted(tree.nodes.items())
    )
    active_nodes = [
        node
        for node in tree.nodes.values()
        if node.lifecycle == OrgLifecycleState.ACTIVE
    ]
    return OrgTreeSummary(
        tree_id=tree.tree_id,
        revision=tree.revision,
        root_node_id=tree.root_node_id,
        active_node_count=len(active_nodes),
        department_count=sum(
            1 for node in tree.nodes.values() if node.node_type == OrgNodeType.DEPARTMENT
        ),
        team_count=sum(
            1 for node in tree.nodes.values() if node.node_type == OrgNodeType.TEAM
        ),
        individual_count=sum(
            1 for node in tree.nodes.values() if node.node_type == OrgNodeType.INDIVIDUAL
        ),
        node_summaries=node_summaries,
    )


def org_node_summary_to_dict(summary: OrgNodeSummary) -> dict[str, Any]:
    return {
        "org_node_id": summary.org_node_id,
        "name": summary.name,
        "node_type": summary.node_type.value,
        "lifecycle": summary.lifecycle.value,
        "parent_id": summary.parent_id,
        "child_count": summary.child_count,
        "member_count": summary.member_count,
        "leader_kind": summary.leader_kind.value,
        "leader_worker_id": summary.leader_worker_id,
        "responsibility_summary": summary.responsibility_summary,
        "applicable_task_types": list(summary.applicable_task_types),
    }


def org_tree_summary_to_dict(summary: OrgTreeSummary) -> dict[str, Any]:
    return {
        "tree_id": summary.tree_id,
        "revision": summary.revision,
        "root_node_id": summary.root_node_id,
        "active_node_count": summary.active_node_count,
        "department_count": summary.department_count,
        "team_count": summary.team_count,
        "individual_count": summary.individual_count,
        "node_summaries": [
            org_node_summary_to_dict(node_summary)
            for node_summary in summary.node_summaries
        ],
    }


def load_org_node_json(text: str) -> OrgNode:
    """Load one organization node from JSON text."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrganizationError(f"Invalid organization node JSON: {exc.msg}") from exc
    return org_node_from_dict(data)


def dump_org_node_json(node: OrgNode) -> str:
    """Dump one organization node as stable, newline-terminated JSON."""
    return json.dumps(org_node_to_dict(node), indent=2) + "\n"


def load_org_tree_json(text: str) -> OrgTree:
    """Load an organization tree from JSON text."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrganizationError(f"Invalid organization tree JSON: {exc.msg}") from exc
    return org_tree_from_dict(data)


def dump_org_tree_json(tree: OrgTree) -> str:
    """Dump an organization tree as stable, newline-terminated JSON."""
    return json.dumps(org_tree_to_dict(tree), indent=2) + "\n"
