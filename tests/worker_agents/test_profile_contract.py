import pytest

from worker_agents.profile import (
    WORKER_PROFILE_SCHEMA_VERSION,
    WorkerAgentProfile,
    WorkerProfileError,
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
