"""Read-only management view models for worker agent operations.

The builders in this module intentionally accept already-loaded records and
summaries. They never open profile-home files or mutate stores; callers remain
responsible for using the governed lifecycle, approval, and retention services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from worker_agents.organization import (
    OrgLeaderKind,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
)
from worker_agents.registry import WorkerLifecycleStatus, WorkerRegistryRecord


SENSITIVE_FIELD_MARKERS = (
    "api_key",
    "authorization",
    "body",
    "content",
    "credential",
    "env",
    "memory_text",
    "private",
    "raw",
    "secret",
    "token",
    "transcript",
)


class ManagementRiskSeverity(StrEnum):
    """Small severity scale shared by management views."""

    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True)
class ManagementSourceRef:
    """Low-sensitivity reference to the source data used by a view model."""

    source_kind: str
    source_id: str
    revision: str = ""
    updated_at: str | None = None


@dataclass(frozen=True)
class ManagementRiskBadge:
    """User-visible risk or status badge without secret-bearing detail."""

    code: str
    label: str
    severity: ManagementRiskSeverity | str = ManagementRiskSeverity.INFO
    source_refs: tuple[ManagementSourceRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", ManagementRiskSeverity(self.severity))
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True)
class WorkerManagementSummary:
    """Low-sensitivity worker row used by dashboard and list views."""

    worker_id: str
    display_name: str
    role: str
    runtime_type: str
    status: str
    department_ids: tuple[str, ...] = ()
    owner_worker_id: str | None = None
    health_status: str = "unknown"
    policy_summary: str = ""
    risk_badges: tuple[ManagementRiskBadge, ...] = ()
    source_ref: ManagementSourceRef | None = None
    public_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "department_ids", tuple(self.department_ids))
        object.__setattr__(self, "risk_badges", tuple(self.risk_badges))
        object.__setattr__(
            self,
            "public_metadata",
            _redact_sensitive_mapping(self.public_metadata),
        )


@dataclass(frozen=True)
class WorkerManagementListItem:
    """Operational worker list row with only controlled action targets."""

    worker_id: str
    display_name: str
    role: str
    runtime_type: str
    status: str
    department_ids: tuple[str, ...]
    health_status: str
    policy_summary: str
    risk_badges: tuple[ManagementRiskBadge, ...]
    action_links: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "department_ids", tuple(self.department_ids))
        object.__setattr__(self, "risk_badges", tuple(self.risk_badges))
        object.__setattr__(
            self,
            "action_links",
            _controlled_worker_action_links(self.worker_id, self.action_links),
        )


@dataclass(frozen=True)
class OrganizationManagementNodeSummary:
    """Low-sensitivity organization node summary for the dashboard snapshot."""

    org_node_id: str
    name: str
    node_type: str
    lifecycle: str
    parent_id: str | None
    child_ids: tuple[str, ...] = ()
    leader_kind: str = OrgLeaderKind.NONE.value
    leader_worker_id: str | None = None
    member_worker_ids: tuple[str, ...] = ()
    individual_worker_id: str | None = None
    collaboration_mode: str = "none"
    read_only: bool = False
    risk_badges: tuple[ManagementRiskBadge, ...] = ()
    source_ref: ManagementSourceRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "child_ids", tuple(self.child_ids))
        object.__setattr__(self, "member_worker_ids", tuple(self.member_worker_ids))
        object.__setattr__(self, "risk_badges", tuple(self.risk_badges))


@dataclass(frozen=True)
class OrganizationTreeViewNode:
    """Nested organization tree node for management UI rendering."""

    summary: OrganizationManagementNodeSummary
    children: tuple["OrganizationTreeViewNode", ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class DepartmentManagementSummary:
    """Low-sensitivity department state and asset summary."""

    department_id: str
    display_name: str
    owner_worker_id: str | None = None
    member_count: int = 0
    active_asset_count: int = 0
    accepted_asset_count: int = 0
    default_chat_available: bool = False
    collaboration_mode: str = "none"
    policy_summary: str = ""
    risk_badges: tuple[ManagementRiskBadge, ...] = ()
    source_ref: ManagementSourceRef | None = None
    public_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_badges", tuple(self.risk_badges))
        object.__setattr__(
            self,
            "public_metadata",
            _redact_sensitive_mapping(self.public_metadata),
        )


@dataclass(frozen=True)
class DashboardDataSources:
    """Inputs used to build a management dashboard snapshot."""

    worker_records: Mapping[str, WorkerRegistryRecord | Mapping[str, Any]]
    organization_tree: OrgTree | Mapping[str, Any] | None = None
    department_summaries: Sequence[DepartmentManagementSummary | Mapping[str, Any]] = ()
    health_summaries: Mapping[str, Mapping[str, Any] | str] = field(default_factory=dict)
    policy_summaries: Mapping[str, str] = field(default_factory=dict)
    source_revision: str = ""
    source_updated_at: str | None = None


@dataclass(frozen=True)
class DashboardSnapshot:
    """Read-only dashboard snapshot for worker and organization management."""

    workers: tuple[WorkerManagementSummary, ...]
    organization_nodes: tuple[OrganizationManagementNodeSummary, ...]
    departments: tuple[DepartmentManagementSummary, ...]
    risk_badges: tuple[ManagementRiskBadge, ...]
    warnings: tuple[str, ...]
    source_ref: ManagementSourceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "workers", tuple(self.workers))
        object.__setattr__(self, "organization_nodes", tuple(self.organization_nodes))
        object.__setattr__(self, "departments", tuple(self.departments))
        object.__setattr__(self, "risk_badges", tuple(self.risk_badges))
        object.__setattr__(self, "warnings", tuple(self.warnings))


def build_dashboard_snapshot(sources: DashboardDataSources) -> DashboardSnapshot:
    """Build a read-only management dashboard from loaded low-sensitivity data."""

    source_ref = ManagementSourceRef(
        source_kind="management_dashboard",
        source_id="worker_agents",
        revision=sources.source_revision,
        updated_at=sources.source_updated_at,
    )
    workers = tuple(
        _build_worker_summary(
            worker_id,
            record,
            health=sources.health_summaries.get(worker_id),
            policy_summary=sources.policy_summaries.get(worker_id, ""),
        )
        for worker_id, record in sorted(sources.worker_records.items())
    )
    worker_ids = {worker.worker_id for worker in workers}
    departments = tuple(
        _coerce_department_summary(summary)
        for summary in sources.department_summaries
    )
    organization_nodes, warnings = _build_organization_summaries(
        sources.organization_tree,
        worker_ids=worker_ids,
    )
    risk_badges = tuple(
        badge
        for item in (*workers, *organization_nodes, *departments)
        for badge in item.risk_badges
    )
    return DashboardSnapshot(
        workers=workers,
        organization_nodes=organization_nodes,
        departments=departments,
        risk_badges=risk_badges,
        warnings=tuple(warnings),
        source_ref=source_ref,
    )


def dashboard_snapshot_to_dict(snapshot: DashboardSnapshot) -> dict[str, Any]:
    """Serialize a dashboard snapshot deterministically for APIs and tests."""

    return {
        "source_ref": source_ref_to_dict(snapshot.source_ref),
        "workers": [worker_summary_to_dict(worker) for worker in snapshot.workers],
        "organization_nodes": [
            organization_node_summary_to_dict(node)
            for node in snapshot.organization_nodes
        ],
        "departments": [
            department_summary_to_dict(department)
            for department in snapshot.departments
        ],
        "risk_badges": [risk_badge_to_dict(badge) for badge in snapshot.risk_badges],
        "warnings": list(snapshot.warnings),
    }


def build_worker_management_list(
    snapshot: DashboardSnapshot,
) -> tuple[WorkerManagementListItem, ...]:
    """Return list-view rows derived from the dashboard snapshot."""

    return tuple(_worker_list_item(worker) for worker in snapshot.workers)


def filter_worker_management_list(
    workers: Iterable[WorkerManagementListItem],
    *,
    status: str | None = None,
    department_id: str | None = None,
    runtime_type: str | None = None,
    risk_badge: str | None = None,
    include_archived: bool = True,
) -> tuple[WorkerManagementListItem, ...]:
    """Filter worker list rows without hiding archived workers by default."""

    result = []
    for worker in workers:
        if not include_archived and worker.status == WorkerLifecycleStatus.ARCHIVED.value:
            continue
        if status is not None and worker.status != status:
            continue
        if department_id is not None and department_id not in worker.department_ids:
            continue
        if runtime_type is not None and worker.runtime_type != runtime_type:
            continue
        if risk_badge is not None and all(
            badge.code != risk_badge for badge in worker.risk_badges
        ):
            continue
        result.append(worker)
    return tuple(result)


def sort_worker_management_list(
    workers: Iterable[WorkerManagementListItem],
    *,
    sort_key: str = "display_name",
) -> tuple[WorkerManagementListItem, ...]:
    """Sort worker list rows by a stable public field."""

    allowed_keys = {
        "display_name",
        "health_status",
        "runtime_type",
        "status",
        "worker_id",
    }
    key = sort_key if sort_key in allowed_keys else "display_name"
    return tuple(sorted(workers, key=lambda worker: (getattr(worker, key), worker.worker_id)))


def build_organization_tree_view(
    nodes: Iterable[OrganizationManagementNodeSummary],
    *,
    root_node_id: str | None = None,
) -> tuple[OrganizationTreeViewNode, ...]:
    """Build nested organization tree view nodes without editing the active tree."""

    node_map = {node.org_node_id: node for node in nodes}
    children_by_parent: dict[str | None, list[OrganizationManagementNodeSummary]] = {}
    for node in node_map.values():
        children_by_parent.setdefault(node.parent_id, []).append(node)
    for children in children_by_parent.values():
        children.sort(key=lambda child: (child.name, child.org_node_id))

    explicit_roots = [node_map[root_node_id]] if root_node_id in node_map else []
    roots = explicit_roots or children_by_parent.get(None, [])
    if not roots:
        referenced_children = {
            child_id for node in node_map.values() for child_id in node.child_ids
        }
        roots = [
            node
            for node in sorted(node_map.values(), key=lambda item: item.org_node_id)
            if node.org_node_id not in referenced_children
        ]
    return tuple(
        _organization_tree_node(root, children_by_parent, visiting=set())
        for root in roots
    )


def organization_tree_view_node_to_dict(
    node: OrganizationTreeViewNode,
) -> dict[str, Any]:
    return {
        "summary": organization_node_summary_to_dict(node.summary),
        "children": [
            organization_tree_view_node_to_dict(child) for child in node.children
        ],
        "warnings": list(node.warnings),
    }


def worker_management_list_item_to_dict(
    item: WorkerManagementListItem,
) -> dict[str, Any]:
    return {
        "worker_id": item.worker_id,
        "display_name": item.display_name,
        "role": item.role,
        "runtime_type": item.runtime_type,
        "status": item.status,
        "department_ids": list(item.department_ids),
        "health_status": item.health_status,
        "policy_summary": item.policy_summary,
        "risk_badges": [risk_badge_to_dict(badge) for badge in item.risk_badges],
        "action_links": dict(item.action_links),
    }


def worker_summary_to_dict(summary: WorkerManagementSummary) -> dict[str, Any]:
    return {
        "worker_id": summary.worker_id,
        "display_name": summary.display_name,
        "role": summary.role,
        "runtime_type": summary.runtime_type,
        "status": summary.status,
        "department_ids": list(summary.department_ids),
        "owner_worker_id": summary.owner_worker_id,
        "health_status": summary.health_status,
        "policy_summary": summary.policy_summary,
        "risk_badges": [risk_badge_to_dict(badge) for badge in summary.risk_badges],
        "source_ref": _optional_source_ref_to_dict(summary.source_ref),
        "public_metadata": dict(summary.public_metadata),
    }


def organization_node_summary_to_dict(
    summary: OrganizationManagementNodeSummary,
) -> dict[str, Any]:
    return {
        "org_node_id": summary.org_node_id,
        "name": summary.name,
        "node_type": summary.node_type,
        "lifecycle": summary.lifecycle,
        "parent_id": summary.parent_id,
        "child_ids": list(summary.child_ids),
        "leader_kind": summary.leader_kind,
        "leader_worker_id": summary.leader_worker_id,
        "member_worker_ids": list(summary.member_worker_ids),
        "individual_worker_id": summary.individual_worker_id,
        "collaboration_mode": summary.collaboration_mode,
        "read_only": summary.read_only,
        "risk_badges": [risk_badge_to_dict(badge) for badge in summary.risk_badges],
        "source_ref": _optional_source_ref_to_dict(summary.source_ref),
    }


def department_summary_to_dict(summary: DepartmentManagementSummary) -> dict[str, Any]:
    return {
        "department_id": summary.department_id,
        "display_name": summary.display_name,
        "owner_worker_id": summary.owner_worker_id,
        "member_count": summary.member_count,
        "active_asset_count": summary.active_asset_count,
        "accepted_asset_count": summary.accepted_asset_count,
        "default_chat_available": summary.default_chat_available,
        "collaboration_mode": summary.collaboration_mode,
        "policy_summary": summary.policy_summary,
        "risk_badges": [risk_badge_to_dict(badge) for badge in summary.risk_badges],
        "source_ref": _optional_source_ref_to_dict(summary.source_ref),
        "public_metadata": dict(summary.public_metadata),
    }


def risk_badge_to_dict(badge: ManagementRiskBadge) -> dict[str, Any]:
    return {
        "code": badge.code,
        "label": badge.label,
        "severity": badge.severity.value,
        "source_refs": [source_ref_to_dict(ref) for ref in badge.source_refs],
    }


def source_ref_to_dict(ref: ManagementSourceRef) -> dict[str, Any]:
    return {
        "source_kind": ref.source_kind,
        "source_id": ref.source_id,
        "revision": ref.revision,
        "updated_at": ref.updated_at,
    }


def _build_worker_summary(
    worker_id: str,
    record: WorkerRegistryRecord | Mapping[str, Any],
    *,
    health: Mapping[str, Any] | str | None,
    policy_summary: str,
) -> WorkerManagementSummary:
    status = _string_from_record(record, "status", WorkerLifecycleStatus.REGISTERED.value)
    if isinstance(getattr(record, "status", None), WorkerLifecycleStatus):
        status = getattr(record, "status").value
    health_status = _health_status(health)
    risks: list[ManagementRiskBadge] = []
    if health_status in {"unhealthy", "failed", "offline"}:
        risks.append(
            ManagementRiskBadge(
                code="external_unhealthy",
                label="External runtime health needs attention",
                severity=ManagementRiskSeverity.WARNING,
                source_refs=(
                    ManagementSourceRef("worker_health", worker_id),
                ),
            )
        )
    return WorkerManagementSummary(
        worker_id=_string_from_record(record, "worker_id", worker_id),
        display_name=_string_from_record(record, "display_name", worker_id),
        role=_string_from_record(record, "role", ""),
        runtime_type=_string_from_record(record, "runtime_type", ""),
        status=status,
        department_ids=_string_tuple_from_metadata(record, "department_ids"),
        owner_worker_id=_optional_string_from_record(record, "owner_worker_id"),
        health_status=health_status,
        policy_summary=policy_summary,
        risk_badges=tuple(risks),
        source_ref=ManagementSourceRef(
            "worker_registry",
            worker_id,
            updated_at=_optional_string_from_record(record, "updated_at"),
        ),
        public_metadata=_mapping_from_record(record, "metadata"),
    )


def _worker_list_item(summary: WorkerManagementSummary) -> WorkerManagementListItem:
    return WorkerManagementListItem(
        worker_id=summary.worker_id,
        display_name=summary.display_name,
        role=summary.role,
        runtime_type=summary.runtime_type,
        status=summary.status,
        department_ids=summary.department_ids,
        health_status=summary.health_status,
        policy_summary=summary.policy_summary,
        risk_badges=summary.risk_badges,
        action_links=_controlled_worker_action_links(summary.worker_id, {}),
    )


def _controlled_worker_action_links(
    worker_id: str,
    requested_links: Mapping[str, str],
) -> dict[str, str]:
    safe_links = {
        "view_approvals": f"approval-center?worker_id={worker_id}",
        "view_operations": f"operations-console?worker_id={worker_id}",
        "view_assets": f"asset-review?worker_id={worker_id}",
    }
    for name, target in requested_links.items():
        if name in safe_links and isinstance(target, str):
            safe_links[name] = target
    return safe_links


def _build_organization_summaries(
    organization_tree: OrgTree | Mapping[str, Any] | None,
    *,
    worker_ids: set[str],
) -> tuple[tuple[OrganizationManagementNodeSummary, ...], list[str]]:
    if organization_tree is None:
        return (), []
    tree = organization_tree if isinstance(organization_tree, OrgTree) else None
    raw_nodes: Iterable[OrgNode | Mapping[str, Any]]
    revision = ""
    updated_at = None
    if tree is not None:
        raw_nodes = (node for _, node in sorted(tree.nodes.items()))
        revision = str(tree.revision)
        updated_at = tree.updated_at
    else:
        raw_nodes = _mapping_values(organization_tree.get("nodes", ()))
        revision = str(organization_tree.get("revision", ""))
        updated_at = _optional_string(organization_tree.get("updated_at"))

    nodes = tuple(
        _build_organization_node_summary(node, worker_ids, revision, updated_at)
        for node in raw_nodes
    )
    node_ids = {node.org_node_id for node in nodes}
    warnings = [
        f"organization node {node.org_node_id!r} references missing child {child_id!r}"
        for node in nodes
        for child_id in node.child_ids
        if child_id not in node_ids
    ]
    warnings.extend(
        f"organization node {node.org_node_id!r} references missing parent {node.parent_id!r}"
        for node in nodes
        if node.parent_id is not None and node.parent_id not in node_ids
    )
    warnings.extend(
        f"organization node {node.org_node_id!r} references missing worker {worker_id!r}"
        for node in nodes
        for worker_id in _node_worker_refs(node)
        if worker_id not in worker_ids
    )
    return nodes, warnings


def _build_organization_node_summary(
    node: OrgNode | Mapping[str, Any],
    worker_ids: set[str],
    revision: str,
    updated_at: str | None,
) -> OrganizationManagementNodeSummary:
    org_node_id = _string_from_record(node, "org_node_id", "")
    lifecycle = _enum_value(_value_from_record(node, "lifecycle"), OrgLifecycleState.DRAFT.value)
    node_type = _enum_value(_value_from_record(node, "node_type"), "")
    leader = _value_from_record(node, "leader")
    leader_kind = _leader_kind(leader)
    leader_worker_id = _leader_worker_id(leader)
    member_worker_ids = _string_tuple_from_record(node, "member_worker_ids")
    individual_worker_id = _optional_string_from_record(node, "individual_worker_id")
    child_ids = _string_tuple_from_record(node, "child_ids")
    risks: list[ManagementRiskBadge] = []
    if leader_kind == OrgLeaderKind.WORKER.value and leader_worker_id not in worker_ids:
        risks.append(_node_risk("missing_owner", "Owner worker is missing", org_node_id))
    for worker_id in (*member_worker_ids, *(() if individual_worker_id is None else (individual_worker_id,))):
        if worker_id not in worker_ids:
            risks.append(_node_risk("missing_worker", "Referenced worker is missing", org_node_id))
    collaboration_mode = _collaboration_mode(node_type, member_worker_ids, individual_worker_id)
    if collaboration_mode == "department_group_chat_unavailable":
        risks.append(_node_risk("chat_binding_invalid", "Default group chat is unavailable", org_node_id))
    return OrganizationManagementNodeSummary(
        org_node_id=org_node_id,
        name=_string_from_record(node, "name", org_node_id),
        node_type=node_type,
        lifecycle=lifecycle,
        parent_id=_optional_string_from_record(node, "parent_id"),
        child_ids=child_ids,
        leader_kind=leader_kind,
        leader_worker_id=leader_worker_id,
        member_worker_ids=member_worker_ids,
        individual_worker_id=individual_worker_id,
        collaboration_mode=collaboration_mode,
        read_only=lifecycle in {OrgLifecycleState.ARCHIVED.value, OrgLifecycleState.DEPRECATED.value},
        risk_badges=tuple(risks),
        source_ref=ManagementSourceRef("organization_tree", org_node_id, revision, updated_at),
    )


def _coerce_department_summary(
    summary: DepartmentManagementSummary | Mapping[str, Any],
) -> DepartmentManagementSummary:
    if isinstance(summary, DepartmentManagementSummary):
        return summary
    member_count = _int_value(summary.get("member_count", 0))
    requested_group_chat = bool(summary.get("default_chat_available", False))
    default_chat_available = requested_group_chat and member_count > 1
    collaboration_mode = _optional_string(summary.get("collaboration_mode")) or (
        "department_group_chat" if default_chat_available else "private_or_parent_chat"
    )
    return DepartmentManagementSummary(
        department_id=str(summary.get("department_id", "")),
        display_name=str(summary.get("display_name", summary.get("department_id", ""))),
        owner_worker_id=_optional_string(summary.get("owner_worker_id")),
        member_count=member_count,
        active_asset_count=_int_value(summary.get("active_asset_count", 0)),
        accepted_asset_count=_int_value(summary.get("accepted_asset_count", 0)),
        default_chat_available=default_chat_available,
        collaboration_mode=collaboration_mode,
        policy_summary=str(summary.get("policy_summary", "")),
        public_metadata=_redact_sensitive_mapping(
            _mapping(summary.get("public_metadata", {}))
        ),
    )


def _redact_sensitive_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if _is_sensitive_key(key_text):
            continue
        if isinstance(value, Mapping):
            result[key_text] = _redact_sensitive_mapping(value)
        elif isinstance(value, (list, tuple)):
            result[key_text] = [
                _redact_sensitive_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            result[key_text] = value
    return result


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_FIELD_MARKERS)


def _node_risk(code: str, label: str, node_id: str) -> ManagementRiskBadge:
    return ManagementRiskBadge(
        code=code,
        label=label,
        severity=ManagementRiskSeverity.WARNING,
        source_refs=(ManagementSourceRef("organization_node", node_id),),
    )


def _organization_tree_node(
    summary: OrganizationManagementNodeSummary,
    children_by_parent: Mapping[str | None, list[OrganizationManagementNodeSummary]],
    *,
    visiting: set[str],
) -> OrganizationTreeViewNode:
    warnings: list[str] = []
    if summary.org_node_id in visiting:
        warnings.append(f"organization tree cycle detected at {summary.org_node_id!r}")
        return OrganizationTreeViewNode(summary=summary, warnings=tuple(warnings))
    visiting.add(summary.org_node_id)
    children = tuple(
        _organization_tree_node(child, children_by_parent, visiting=visiting)
        for child in children_by_parent.get(summary.org_node_id, [])
    )
    visiting.remove(summary.org_node_id)
    if summary.read_only:
        warnings.append(f"organization node {summary.org_node_id!r} is read-only")
    return OrganizationTreeViewNode(
        summary=summary,
        children=children,
        warnings=tuple(warnings),
    )


def _collaboration_mode(
    node_type: str,
    member_worker_ids: tuple[str, ...],
    individual_worker_id: str | None,
) -> str:
    if node_type == OrgNodeType.INDIVIDUAL.value or individual_worker_id:
        return "private_chat"
    if len(member_worker_ids) <= 1:
        return "private_or_parent_chat"
    if node_type == OrgNodeType.DEPARTMENT.value:
        return "department_group_chat"
    return "parent_chat"


def _node_worker_refs(node: OrganizationManagementNodeSummary) -> tuple[str, ...]:
    refs = list(node.member_worker_ids)
    if node.individual_worker_id:
        refs.append(node.individual_worker_id)
    if node.leader_worker_id:
        refs.append(node.leader_worker_id)
    return tuple(refs)


def _mapping_values(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Mapping):
        return tuple(value[key] for key in sorted(value))
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _health_status(health: Mapping[str, Any] | str | None) -> str:
    if health is None:
        return "unknown"
    if isinstance(health, str):
        return health
    raw = health.get("status", "unknown")
    return raw if isinstance(raw, str) else "unknown"


def _string_tuple_from_metadata(record: WorkerRegistryRecord | Mapping[str, Any], key: str) -> tuple[str, ...]:
    metadata = _mapping_from_record(record, "metadata")
    return _string_tuple(metadata.get(key, ()))


def _string_tuple_from_record(record: Any, key: str) -> tuple[str, ...]:
    return _string_tuple(_value_from_record(record, key) or ())


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _mapping_from_record(record: Any, key: str) -> Mapping[str, Any]:
    value = _value_from_record(record, key)
    return value if isinstance(value, Mapping) else {}


def _string_from_record(record: Any, key: str, default: str) -> str:
    value = _value_from_record(record, key)
    if isinstance(value, StrEnum):
        return value.value
    return value if isinstance(value, str) and value else default


def _optional_string_from_record(record: Any, key: str) -> str | None:
    return _optional_string(_value_from_record(record, key))


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _value_from_record(record: Any, key: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(key)
    return getattr(record, key, None)


def _enum_value(value: Any, default: str) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return value if isinstance(value, str) and value else default


def _leader_kind(leader: Any) -> str:
    if isinstance(leader, Mapping):
        return _enum_value(leader.get("kind"), OrgLeaderKind.NONE.value)
    return _enum_value(getattr(leader, "kind", None), OrgLeaderKind.NONE.value)


def _leader_worker_id(leader: Any) -> str | None:
    if isinstance(leader, Mapping):
        return _optional_string(leader.get("worker_id"))
    return _optional_string(getattr(leader, "worker_id", None))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_value(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _optional_source_ref_to_dict(ref: ManagementSourceRef | None) -> dict[str, Any] | None:
    return source_ref_to_dict(ref) if ref is not None else None
