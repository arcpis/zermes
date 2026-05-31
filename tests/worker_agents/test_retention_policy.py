import pytest

from worker_agents.retention import (
    RETENTION_POLICY_SCHEMA_VERSION,
    RetentionAction,
    RetentionDataCategory,
    RetentionPolicy,
    RetentionPolicyError,
    RetentionPolicyStore,
    RetentionRule,
    default_retention_policy,
    retention_policy_from_dict,
    retention_policy_to_dict,
)


def test_policy_store_loads_conservative_default_when_file_is_missing(tmp_path):
    store = RetentionPolicyStore(tmp_path / "profile" / "worker_agents")

    policy = store.load_policy()

    assert policy.rule_for(RetentionDataCategory.PROTECTED_LONG_TERM).action == (
        RetentionAction.NEVER_DELETE
    )
    assert policy.rule_for(RetentionDataCategory.RUNTIME_ACTIVE).action == (
        RetentionAction.NEVER_DELETE
    )
    assert policy.rule_for(RetentionDataCategory.RUNTIME_ORPHANED).action == (
        RetentionAction.REVIEW_REQUIRED
    )
    assert not store.policy_path.exists()


def test_policy_store_saves_and_reloads_policy(tmp_path):
    store = RetentionPolicyStore(tmp_path / "profile" / "worker_agents")
    policy = default_retention_policy()

    path = store.save_policy(policy)
    loaded = store.load_policy()

    assert path == store.shared_dir / "retention-policy.json"
    assert retention_policy_to_dict(loaded) == retention_policy_to_dict(policy)


def test_retention_policy_serialization_is_stable():
    policy = default_retention_policy()

    data = retention_policy_to_dict(policy)
    loaded = retention_policy_from_dict(data)

    assert data["schema_version"] == RETENTION_POLICY_SCHEMA_VERSION
    assert retention_policy_to_dict(loaded) == data


def test_retention_policy_rejects_unknown_category():
    data = retention_policy_to_dict(default_retention_policy())
    data["rules"][0]["category"] = "mystery"

    with pytest.raises(RetentionPolicyError, match="Unknown retention data category"):
        retention_policy_from_dict(data)


def test_retention_policy_rejects_unknown_action():
    data = retention_policy_to_dict(default_retention_policy())
    data["rules"][0]["action"] = "erase_everything"

    with pytest.raises(RetentionPolicyError, match="Unknown retention action"):
        retention_policy_from_dict(data)


def test_retention_policy_rejects_invalid_retention_days():
    with pytest.raises(RetentionPolicyError, match="retention_days"):
        RetentionRule(
            category=RetentionDataCategory.CACHE_REBUILDABLE,
            action=RetentionAction.DELETE_WHEN_EXPIRED,
            retention_days=-1,
        )


def test_retention_policy_rejects_deletable_long_term_rule():
    with pytest.raises(RetentionPolicyError, match="must never be deleted"):
        RetentionRule(
            category=RetentionDataCategory.PROTECTED_LONG_TERM,
            action=RetentionAction.DELETE_WHEN_EXPIRED,
            retention_days=30,
        )


def test_retention_policy_requires_all_categories():
    rules = dict(default_retention_policy().rules)
    rules.pop(RetentionDataCategory.RUNTIME_ACTIVE)

    with pytest.raises(RetentionPolicyError, match="missing rules"):
        RetentionPolicy(rules=rules)
