from worker_agents import (
    PRIVATE_ASSET_SCHEMA_VERSION,
    PrivateAssetKind,
    PrivateAssetSensitivity,
    PrivateAssetShareStatus,
    PrivateMemoryRecord,
    PrivateSkillExperience,
    SkillExperienceKind,
    ToolPolicyCandidate,
    ToolPolicyViolationCode,
    WorkerToolPermissionSnapshot,
    build_tool_permission_snapshot,
    private_memory_to_proposal_input,
    skill_experience_to_proposal_input,
    validate_private_asset_payload,
)
from worker_agents.profile import WorkerAgentProfile


def test_private_asset_boundaries_are_available_from_package():
    assert PRIVATE_ASSET_SCHEMA_VERSION == 1
    assert PrivateAssetKind.PRIVATE_MEMORY.value == "private_memory"
    assert PrivateAssetSensitivity.LOW.value == "low"
    assert PrivateAssetShareStatus.PRIVATE_ONLY.value == "private_only"
    assert PrivateMemoryRecord.__name__ == "PrivateMemoryRecord"
    assert private_memory_to_proposal_input.__name__ == "private_memory_to_proposal_input"
    assert validate_private_asset_payload.__name__ == "validate_private_asset_payload"


def test_private_skill_and_tool_snapshot_exports_are_available_from_package():
    assert PrivateSkillExperience.__name__ == "PrivateSkillExperience"
    assert SkillExperienceKind.TASK_LESSON.value == "task_lesson"
    assert skill_experience_to_proposal_input.__name__ == (
        "skill_experience_to_proposal_input"
    )
    assert ToolPolicyCandidate.__name__ == "ToolPolicyCandidate"
    assert ToolPolicyViolationCode.TOOL_NOT_IN_PROFILE.value == "tool_not_in_profile"
    assert WorkerToolPermissionSnapshot.__name__ == "WorkerToolPermissionSnapshot"

    profile = WorkerAgentProfile(
        worker_id="frontend",
        display_name="Frontend",
        description="Builds UI features.",
        role="frontend",
    )
    assert build_tool_permission_snapshot(profile).allowed_tools == ()
