"""Retention policy contract for managed worker-agent runtime data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from .storage.paths import get_worker_agents_home


RETENTION_POLICY_SCHEMA_VERSION = 1
RETENTION_POLICY_FILE_NAME = "retention-policy.json"


class RetentionPolicyError(ValueError):
    """Raised when a worker-agent retention policy is invalid."""


class RetentionDataCategory(StrEnum):
    """Known retention categories for worker-agent storage."""

    PROTECTED_LONG_TERM = "protected_long_term"
    RUNTIME_ACTIVE = "runtime_active"
    RUNTIME_RECENT_TERMINAL = "runtime_recent_terminal"
    RUNTIME_EXPIRED_TERMINAL = "runtime_expired_terminal"
    RUNTIME_NEEDS_REVIEW = "runtime_needs_review"
    RUNTIME_ORPHANED = "runtime_orphaned"
    CACHE_REBUILDABLE = "cache_rebuildable"
    TRANSCRIPT_SENSITIVE = "transcript_sensitive"


class RetentionAction(StrEnum):
    """Action a cleanup planner may recommend for a category."""

    NEVER_DELETE = "never_delete"
    KEEP_UNTIL_EXPIRED = "keep_until_expired"
    DELETE_WHEN_EXPIRED = "delete_when_expired"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True)
class RetentionRule:
    """Retention behavior for one category of worker-agent data."""

    category: RetentionDataCategory
    action: RetentionAction
    retention_days: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _coerce_category(self.category))
        object.__setattr__(self, "action", _coerce_action(self.action))
        if self.retention_days is not None:
            if (
                isinstance(self.retention_days, bool)
                or not isinstance(self.retention_days, int)
                or self.retention_days < 0
            ):
                raise RetentionPolicyError(
                    "retention_days must be a non-negative integer or null"
                )
        if self.category == RetentionDataCategory.PROTECTED_LONG_TERM:
            if self.action != RetentionAction.NEVER_DELETE:
                raise RetentionPolicyError(
                    "protected long-term worker-agent data must never be deleted"
                )
            if self.retention_days is not None:
                raise RetentionPolicyError(
                    "protected long-term worker-agent data cannot expire"
                )
        if self.action == RetentionAction.NEVER_DELETE and self.retention_days is not None:
            raise RetentionPolicyError("never_delete rules cannot set retention_days")


@dataclass(frozen=True)
class RetentionPolicy:
    """Versioned policy used by cleanup planning and execution."""

    rules: Mapping[RetentionDataCategory, RetentionRule] = field(default_factory=dict)
    schema_version: int = RETENTION_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RETENTION_POLICY_SCHEMA_VERSION:
            raise RetentionPolicyError(
                f"Unsupported retention policy schema_version: {self.schema_version!r}"
            )
        normalized_rules: dict[RetentionDataCategory, RetentionRule] = {}
        for category, rule in self.rules.items():
            normalized_category = _coerce_category(category)
            if rule.category != normalized_category:
                raise RetentionPolicyError("retention rule category does not match key")
            normalized_rules[normalized_category] = rule
        missing = set(RetentionDataCategory) - set(normalized_rules)
        if missing:
            names = ", ".join(sorted(category.value for category in missing))
            raise RetentionPolicyError(f"retention policy is missing rules: {names}")
        object.__setattr__(self, "rules", normalized_rules)

    def rule_for(self, category: RetentionDataCategory | str) -> RetentionRule:
        """Return the rule for ``category`` after validating the category name."""
        return self.rules[_coerce_category(category)]


@dataclass
class RetentionPolicyStore:
    """Durable profile-home store for worker-agent retention policy."""

    root: Path = field(default_factory=get_worker_agents_home)

    @property
    def shared_dir(self) -> Path:
        return self.root / "shared"

    @property
    def policy_path(self) -> Path:
        return self.shared_dir / RETENTION_POLICY_FILE_NAME

    def load_policy(self) -> RetentionPolicy:
        """Load the configured policy, falling back to conservative defaults."""
        if not self.policy_path.exists():
            return default_retention_policy()
        try:
            data = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RetentionPolicyError(
                f"Invalid worker-agent retention policy JSON: {exc.msg}"
            ) from exc
        return retention_policy_from_dict(data)

    def save_policy(self, policy: RetentionPolicy) -> Path:
        """Persist a validated retention policy in durable profile storage."""
        atomic_json_write(self.policy_path, retention_policy_to_dict(policy))
        return self.policy_path


def default_retention_policy() -> RetentionPolicy:
    """Return the conservative built-in retention policy."""
    rules = {
        RetentionDataCategory.PROTECTED_LONG_TERM: RetentionRule(
            category=RetentionDataCategory.PROTECTED_LONG_TERM,
            action=RetentionAction.NEVER_DELETE,
        ),
        RetentionDataCategory.RUNTIME_ACTIVE: RetentionRule(
            category=RetentionDataCategory.RUNTIME_ACTIVE,
            action=RetentionAction.NEVER_DELETE,
        ),
        RetentionDataCategory.RUNTIME_RECENT_TERMINAL: RetentionRule(
            category=RetentionDataCategory.RUNTIME_RECENT_TERMINAL,
            action=RetentionAction.KEEP_UNTIL_EXPIRED,
            retention_days=30,
        ),
        RetentionDataCategory.RUNTIME_EXPIRED_TERMINAL: RetentionRule(
            category=RetentionDataCategory.RUNTIME_EXPIRED_TERMINAL,
            action=RetentionAction.DELETE_WHEN_EXPIRED,
            retention_days=30,
        ),
        RetentionDataCategory.RUNTIME_NEEDS_REVIEW: RetentionRule(
            category=RetentionDataCategory.RUNTIME_NEEDS_REVIEW,
            action=RetentionAction.REVIEW_REQUIRED,
        ),
        RetentionDataCategory.RUNTIME_ORPHANED: RetentionRule(
            category=RetentionDataCategory.RUNTIME_ORPHANED,
            action=RetentionAction.REVIEW_REQUIRED,
        ),
        RetentionDataCategory.CACHE_REBUILDABLE: RetentionRule(
            category=RetentionDataCategory.CACHE_REBUILDABLE,
            action=RetentionAction.DELETE_WHEN_EXPIRED,
            retention_days=3,
        ),
        RetentionDataCategory.TRANSCRIPT_SENSITIVE: RetentionRule(
            category=RetentionDataCategory.TRANSCRIPT_SENSITIVE,
            action=RetentionAction.DELETE_WHEN_EXPIRED,
            retention_days=7,
        ),
    }
    return RetentionPolicy(rules=rules)


def retention_policy_from_dict(data: Mapping[str, Any]) -> RetentionPolicy:
    """Build a retention policy from a strict JSON dictionary."""
    data = _require_mapping(data, "retention policy")
    _reject_unknown_fields(data, {"schema_version", "rules"}, "retention policy")
    schema_version = data.get("schema_version")
    if schema_version != RETENTION_POLICY_SCHEMA_VERSION:
        raise RetentionPolicyError(
            f"Unsupported retention policy schema_version: {schema_version!r}"
        )
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        raise RetentionPolicyError("retention policy rules must be a list")
    rules: dict[RetentionDataCategory, RetentionRule] = {}
    for raw_rule in raw_rules:
        rule = retention_rule_from_dict(raw_rule)
        if rule.category in rules:
            raise RetentionPolicyError(
                f"duplicate retention rule for category: {rule.category.value}"
            )
        rules[rule.category] = rule
    return RetentionPolicy(schema_version=schema_version, rules=rules)


def retention_policy_to_dict(policy: RetentionPolicy) -> dict[str, Any]:
    """Convert a retention policy to deterministic JSON-ready data."""
    return {
        "schema_version": policy.schema_version,
        "rules": [
            retention_rule_to_dict(policy.rules[category])
            for category in sorted(policy.rules, key=lambda item: item.value)
        ],
    }


def retention_rule_from_dict(data: Mapping[str, Any]) -> RetentionRule:
    """Build one retention rule from a strict JSON dictionary."""
    data = _require_mapping(data, "retention rule")
    _reject_unknown_fields(
        data, {"category", "action", "retention_days"}, "retention rule"
    )
    return RetentionRule(
        category=_coerce_category(_require_string(data.get("category"), "category")),
        action=_coerce_action(_require_string(data.get("action"), "action")),
        retention_days=_optional_non_negative_int(
            data.get("retention_days"), "retention_days"
        ),
    )


def retention_rule_to_dict(rule: RetentionRule) -> dict[str, Any]:
    """Convert one retention rule to deterministic JSON-ready data."""
    return {
        "category": rule.category.value,
        "action": rule.action.value,
        "retention_days": rule.retention_days,
    }


def _coerce_category(value: RetentionDataCategory | str) -> RetentionDataCategory:
    if isinstance(value, RetentionDataCategory):
        return value
    try:
        return RetentionDataCategory(_require_string(value, "category"))
    except ValueError as exc:
        raise RetentionPolicyError(f"Unknown retention data category: {value!r}") from exc


def _coerce_action(value: RetentionAction | str) -> RetentionAction:
    if isinstance(value, RetentionAction):
        return value
    try:
        return RetentionAction(_require_string(value, "action"))
    except ValueError as exc:
        raise RetentionPolicyError(f"Unknown retention action: {value!r}") from exc


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RetentionPolicyError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RetentionPolicyError(f"{field_name} must be a non-empty string")
    return value


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetentionPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise RetentionPolicyError(f"{field_name} has unknown fields: {joined}")
