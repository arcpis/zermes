"""Durable organization contract for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .profile import WorkerProfileError, validate_worker_id


ORGANIZATION_SCHEMA_VERSION = 1
MAIN_AGENT_ID = "zermes_main_agent"


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


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OrganizationError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise OrganizationError(f"{field_name} must be a list of non-empty strings")
    return result


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
    schema_version: int = ORGANIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_org_node_id(self.org_node_id)
        object.__setattr__(self, "node_type", _coerce_node_type(self.node_type))
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
        allow_default_group_chat=bool(data.get("allow_default_group_chat", False)),
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
        description=_require_string(data.get("description", ""), "description"),
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
