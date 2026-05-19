import pytest

from worker_agents.profile import (
    WORKER_PROFILE_SCHEMA_VERSION,
    WorkerAgentProfile,
    WorkerProfileError,
    WorkerToolPolicy,
    WorkerWorkspacePolicy,
    dump_worker_profile_json,
    load_worker_profile_json,
    worker_profile_from_dict,
    worker_profile_to_dict,
)


def test_default_worker_profile_uses_minimum_permissions():
    profile = WorkerAgentProfile(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )

    assert profile.schema_version == WORKER_PROFILE_SCHEMA_VERSION
    assert profile.tools.allowed_tools == ()
    assert profile.workspace.write_roots == ()
    assert profile.communication.allow_direct_user_chat is False
    assert profile.communication.allow_group_chat is False
    assert profile.delegation.allow_temporary_child_agents is False
    assert profile.delegation.allowed_child_tools == ()
    assert profile.budgets.max_task_tokens == 0


@pytest.mark.parametrize("worker_id", ["", ".", "..", "team/researcher", r"team\researcher"])
def test_worker_profile_rejects_path_like_worker_ids(worker_id):
    with pytest.raises(WorkerProfileError):
        WorkerAgentProfile(
            worker_id=worker_id,
            display_name="Researcher",
            description="Finds and summarizes information.",
            role="research",
        )


def test_worker_profile_rejects_unknown_schema_version():
    with pytest.raises(WorkerProfileError):
        WorkerAgentProfile(
            worker_id="researcher",
            display_name="Researcher",
            description="Finds and summarizes information.",
            role="research",
            schema_version=WORKER_PROFILE_SCHEMA_VERSION + 1,
        )


def test_worker_profile_round_trips_through_json():
    profile = WorkerAgentProfile(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
        responsibilities=("search", "summarize"),
        tools=WorkerToolPolicy(allowed_tools=("web_search",)),
        workspace=WorkerWorkspacePolicy(read_roots=("docs",), write_roots=()),
    )

    loaded = load_worker_profile_json(dump_worker_profile_json(profile))

    assert loaded == profile


def test_worker_profile_from_dict_applies_minimum_permission_defaults():
    profile = worker_profile_from_dict(
        {
            "worker_id": "researcher",
            "schema_version": WORKER_PROFILE_SCHEMA_VERSION,
            "display_name": "Researcher",
            "description": "Finds and summarizes information.",
            "role": "research",
        }
    )

    assert profile.tools.allowed_tools == ()
    assert profile.workspace.write_roots == ()
    assert profile.delegation.allow_temporary_child_agents is False
    assert profile.budgets.max_task_tokens == 0


def test_worker_profile_from_dict_rejects_missing_identity_fields():
    with pytest.raises(WorkerProfileError, match="display_name"):
        worker_profile_from_dict(
            {
                "worker_id": "researcher",
                "schema_version": WORKER_PROFILE_SCHEMA_VERSION,
                "description": "Finds and summarizes information.",
                "role": "research",
            }
        )


def test_worker_profile_from_dict_rejects_unknown_fields():
    with pytest.raises(WorkerProfileError, match="unknown fields"):
        worker_profile_from_dict(
            {
                "worker_id": "researcher",
                "schema_version": WORKER_PROFILE_SCHEMA_VERSION,
                "display_name": "Researcher",
                "description": "Finds and summarizes information.",
                "role": "research",
                "secret_token": "nope",
            }
        )


def test_worker_profile_from_dict_rejects_unknown_nested_fields():
    with pytest.raises(WorkerProfileError, match="tools has unknown fields"):
        worker_profile_from_dict(
            {
                "worker_id": "researcher",
                "schema_version": WORKER_PROFILE_SCHEMA_VERSION,
                "display_name": "Researcher",
                "description": "Finds and summarizes information.",
                "role": "research",
                "tools": {"allowed_tools": [], "ambient_admin": True},
            }
        )


def test_worker_profile_from_dict_rejects_unknown_schema_version():
    with pytest.raises(WorkerProfileError, match="schema_version"):
        worker_profile_from_dict(
            {
                "worker_id": "researcher",
                "schema_version": WORKER_PROFILE_SCHEMA_VERSION + 1,
                "display_name": "Researcher",
                "description": "Finds and summarizes information.",
                "role": "research",
            }
        )


def test_worker_profile_json_output_is_stable():
    profile = WorkerAgentProfile(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )

    assert dump_worker_profile_json(profile) == dump_worker_profile_json(profile)
    assert list(worker_profile_to_dict(profile)) == [
        "worker_id",
        "schema_version",
        "display_name",
        "description",
        "role",
        "responsibilities",
        "runtime",
        "memory",
        "skills",
        "tools",
        "workspace",
        "communication",
        "model",
        "budgets",
        "limits",
        "cost_policy",
        "delegation",
        "metadata",
    ]
