import pytest

from worker_agents.department_chats import (
    DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION,
    DepartmentChatBinding,
    DepartmentChatBindingState,
    DepartmentChatBindingType,
    DepartmentChatError,
    department_chat_binding_from_dict,
    department_chat_binding_to_dict,
    dump_department_chat_binding_json,
    load_department_chat_binding_json,
    required_department_chat_participants,
    summarize_department_chat_binding,
)
from worker_agents.message_router import ChatParticipantKind, ChatParticipantRef


def _required():
    return required_department_chat_participants("user")


def test_department_chat_binding_round_trips_through_json():
    binding = DepartmentChatBinding(
        binding_id="engineering-default",
        org_node_id="engineering",
        thread_id="engineering-thread",
        binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
        owner_worker_id="engineering_lead",
        member_worker_ids=("engineering_lead", "backend"),
        required_participants=_required(),
        parent_summary_targets=("root",),
        created_at="2026-05-20T00:00:00Z",
        audit_summary="Engineering default department chat.",
    )

    loaded = load_department_chat_binding_json(
        dump_department_chat_binding_json(binding)
    )

    assert loaded == binding
    assert loaded.schema_version == DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION


@pytest.mark.parametrize("binding_type", list(DepartmentChatBindingType))
def test_department_chat_binding_accepts_supported_binding_types(binding_type):
    binding = DepartmentChatBinding(
        binding_id=f"{binding_type.value}-binding",
        org_node_id="engineering",
        thread_id=f"{binding_type.value}-thread",
        binding_type=binding_type,
        required_participants=_required(),
    )

    assert binding.binding_type == binding_type


@pytest.mark.parametrize("state", list(DepartmentChatBindingState))
def test_department_chat_binding_accepts_supported_states(state):
    binding = DepartmentChatBinding(
        binding_id=f"{state.value}-binding",
        org_node_id="engineering",
        thread_id=f"{state.value}-thread",
        binding_type=DepartmentChatBindingType.TEAM_DEFAULT,
        state=state,
        required_participants=_required(),
    )

    assert binding.state == state


@pytest.mark.parametrize("bad_id", ["", ".", "..", "nested/path", r"nested\path"])
def test_department_chat_binding_rejects_path_like_ids(bad_id):
    with pytest.raises(DepartmentChatError):
        DepartmentChatBinding(
            binding_id=bad_id,
            org_node_id="engineering",
            thread_id="engineering-thread",
            binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
            required_participants=_required(),
        )


def test_department_chat_binding_requires_user_and_main_agent():
    with pytest.raises(DepartmentChatError, match="main agent"):
        DepartmentChatBinding(
            binding_id="engineering-default",
            org_node_id="engineering",
            thread_id="engineering-thread",
            binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
            required_participants=(
                ChatParticipantRef(ChatParticipantKind.USER, "user"),
            ),
        )


def test_required_participants_exclude_workers():
    with pytest.raises(DepartmentChatError, match="only include"):
        DepartmentChatBinding(
            binding_id="engineering-default",
            org_node_id="engineering",
            thread_id="engineering-thread",
            binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
            required_participants=(
                *_required(),
                ChatParticipantRef(ChatParticipantKind.WORKER, "backend"),
            ),
        )


def test_department_chat_binding_rejects_duplicate_members():
    with pytest.raises(DepartmentChatError, match="duplicates"):
        DepartmentChatBinding(
            binding_id="engineering-default",
            org_node_id="engineering",
            thread_id="engineering-thread",
            binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
            owner_worker_id="backend",
            member_worker_ids=("backend", "backend"),
            required_participants=_required(),
        )


def test_department_chat_binding_rejects_unknown_fields():
    with pytest.raises(DepartmentChatError, match="unknown fields"):
        department_chat_binding_from_dict(
            {
                "binding_id": "engineering-default",
                "schema_version": DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION,
                "org_node_id": "engineering",
                "thread_id": "engineering-thread",
                "binding_type": "department_default",
                "required_participants": [
                    {"kind": "user", "participant_id": "user"},
                    {
                        "kind": "main_agent",
                        "participant_id": "zermes_main_agent",
                    },
                ],
                "private_memory": "do not store this here",
            }
        )


def test_department_chat_binding_dict_keeps_only_references():
    binding = DepartmentChatBinding(
        binding_id="engineering-default",
        org_node_id="engineering",
        thread_id="engineering-thread",
        binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
        owner_worker_id="engineering_lead",
        member_worker_ids=("engineering_lead", "backend"),
        required_participants=_required(),
    )

    data = department_chat_binding_to_dict(binding)
    summary = summarize_department_chat_binding(binding)

    assert data["member_worker_ids"] == ["engineering_lead", "backend"]
    assert summary.member_count == 2
    assert "profile" not in data
    assert "private_memory" not in data
    assert "skills" not in data
    assert "credentials" not in data
    assert "transcript" not in data
