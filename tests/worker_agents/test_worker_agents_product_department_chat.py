import json

from hermes_cli import worker_agents_product as product


def _worker(worker_id: str, *, status: str = "enabled") -> dict:
    return {
        "worker_id": worker_id,
        "display_name": worker_id.replace("-", " ").title(),
        "runtime_type": "internal",
        "status": status,
    }


def _department_node(
    node_id: str,
    *,
    parent_id: str = "root",
    leader_worker_id: str,
    member_worker_ids: list[str] | None = None,
    child_ids: list[str] | None = None,
) -> dict:
    members = member_worker_ids if member_worker_ids is not None else [leader_worker_id]
    return {
        "schema_version": 1,
        "org_node_id": node_id,
        "name": node_id.replace("-", " ").title(),
        "node_type": "department",
        "description": "",
        "responsibilities": [],
        "parent_id": parent_id,
        "child_ids": child_ids or [],
        "leader": {"kind": "worker", "worker_id": leader_worker_id},
        "member_worker_ids": members,
        "chat_policy": {
            "default_thread_policy": "department_default",
            "allow_default_group_chat": True,
        },
        "lifecycle": "active",
    }


def _state(*, nodes: dict, workers: dict, threads: list[dict] | None = None) -> dict:
    return {
        "worker_records": workers,
        "organization_tree": {
            "schema_version": 1,
            "tree_id": "active",
            "root_node_id": "root",
            "revision": 1,
            "nodes": {
                "root": {
                    "schema_version": 1,
                    "org_node_id": "root",
                    "name": "Root",
                    "node_type": "root",
                    "description": "",
                    "responsibilities": [],
                    "parent_id": None,
                    "child_ids": list(nodes),
                    "leader": {"kind": "main_agent"},
                    "member_worker_ids": [],
                    "chat_policy": {
                        "default_thread_policy": "none",
                        "allow_default_group_chat": False,
                    },
                    "lifecycle": "active",
                },
                **nodes,
            },
        },
        "department_summaries": [],
        "threads": threads or [],
    }


def test_ensure_department_chat_skips_owner_only_department():
    product.write_management_state_for_tests(
        _state(
            nodes={
                "engineering": _department_node(
                    "engineering",
                    leader_worker_id="engineering-lead",
                )
            },
            workers={"engineering-lead": _worker("engineering-lead")},
        )
    )

    result = product.ensure_department_chat(org_node_id="engineering")

    assert result["updated_status"] == "skipped"
    assert product.load_management_state()["threads"] == []
    assert product.list_chats() == []


def test_ensure_department_chat_uses_direct_child_leaders_without_child_members():
    product.write_management_state_for_tests(
        _state(
            nodes={
                "engineering": _department_node(
                    "engineering",
                    leader_worker_id="engineering-lead",
                    child_ids=["platform"],
                ),
                "platform": _department_node(
                    "platform",
                    parent_id="engineering",
                    leader_worker_id="platform-lead",
                    member_worker_ids=["platform-lead", "platform-worker"],
                ),
            },
            workers={
                "engineering-lead": _worker("engineering-lead"),
                "platform-lead": _worker("platform-lead"),
                "platform-worker": _worker("platform-worker"),
            },
        )
    )

    result = product.ensure_department_chat(org_node_id="engineering")

    assert result["updated_status"] == "created"
    state = product.load_management_state()
    thread = state["threads"][0]
    worker_participants = [
        participant["participant_id"]
        for participant in thread["participants"]
        if participant["kind"] == "worker"
    ]
    assert worker_participants == ["engineering-lead", "platform-lead"]
    assert "platform-worker" not in worker_participants
    assert "User: user" in thread["last_summary"]
    assert "Department owner: engineering-lead" in thread["last_summary"]
    assert "Direct members: platform-lead" in thread["last_summary"]


def test_ensure_department_chat_reuses_existing_thread_without_overwrite():
    existing_thread = {
        "thread_id": "dept-engineering",
        "thread_type": "organization_group",
        "participants": [
            {"kind": "user", "participant_id": "user"},
            {"kind": "main_agent", "participant_id": "zermes_main_agent"},
            {"kind": "worker", "participant_id": "engineering-lead"},
            {"kind": "worker", "participant_id": "backend"},
        ],
        "title": "Do Not Rename",
        "status": "active",
        "last_summary": "historical summary",
    }
    product.write_management_state_for_tests(
        _state(
            nodes={
                "engineering": _department_node(
                    "engineering",
                    leader_worker_id="engineering-lead",
                    member_worker_ids=["engineering-lead", "backend"],
                )
            },
            workers={
                "engineering-lead": _worker("engineering-lead"),
                "backend": _worker("backend"),
            },
            threads=[existing_thread],
        )
    )

    result = product.ensure_department_chat(org_node_id="engineering")

    assert result["updated_status"] == "existing"
    assert product.load_management_state()["threads"] == [existing_thread]


def test_apply_evolution_draft_creates_parent_department_chat_side_effect():
    product.write_management_state_for_tests(
        _state(
            nodes={
                "engineering": _department_node(
                    "engineering",
                    leader_worker_id="engineering-lead",
                )
            },
            workers={"engineering-lead": _worker("engineering-lead")},
        )
    )

    result = product.apply_evolution_draft(
        proposal_kind="create_child_agent",
        actor_id="user",
        target_node_id="engineering",
        requested_worker_id="platform-lead",
        reason="Own platform reliability",
    )

    assert result["department_chat"]["updated_status"] == "created"
    threads = product.load_management_state()["threads"]
    assert [thread["thread_id"] for thread in threads] == ["dept-engineering"]


def test_materialize_and_persist_threads_writes_thread_metadata(tmp_path):
    state = _state(
        nodes={
            "engineering": _department_node(
                "engineering",
                leader_worker_id="engineering-lead",
                member_worker_ids=["engineering-lead", "backend"],
            )
        },
        workers={
            "engineering-lead": _worker("engineering-lead"),
            "backend": _worker("backend"),
        },
    )
    product.write_management_state_for_tests(state, home=tmp_path)

    changed = product.materialize_and_persist_threads(
        org_node_ids=["engineering"],
        organization_tree=state["organization_tree"],
        worker_records=state["worker_records"],
        home=tmp_path,
    )

    assert [thread["thread_id"] for thread in changed] == ["dept-engineering"]
    persisted_state = product.load_management_state(home=tmp_path)
    assert [thread["thread_id"] for thread in persisted_state["threads"]] == [
        "dept-engineering"
    ]
    thread_path = tmp_path / "worker_agents" / "threads" / "dept-engineering" / "thread.json"
    index_path = tmp_path / "worker_agents" / "threads" / "_index.json"
    assert json.loads(thread_path.read_text(encoding="utf-8"))["status"] == "active"
    assert json.loads(index_path.read_text(encoding="utf-8"))["threads"] == [
        {
            "org_node_id": "engineering",
            "status": "active",
            "thread_id": "dept-engineering",
            "thread_type": "organization_group",
            "updated_at": changed[0]["updated_at"],
            "worker_id": None,
        }
    ]


def test_materialize_and_persist_threads_archives_stale_department_chat(tmp_path):
    existing_thread = {
        "thread_id": "dept-engineering",
        "thread_type": "organization_group",
        "participants": [
            {"kind": "user", "participant_id": "user"},
            {"kind": "main_agent", "participant_id": "zermes_main_agent"},
            {"kind": "worker", "participant_id": "engineering-lead"},
            {"kind": "worker", "participant_id": "backend"},
        ],
        "title": "Engineering",
        "status": "active",
        "last_summary": "historical summary",
    }
    state = _state(
        nodes={
            "engineering": _department_node(
                "engineering",
                leader_worker_id="engineering-lead",
                member_worker_ids=["engineering-lead", "backend"],
            )
        },
        workers={
            "engineering-lead": _worker("engineering-lead"),
            "backend": _worker("backend", status="archived"),
        },
        threads=[existing_thread],
    )
    product.write_management_state_for_tests(state, home=tmp_path)

    changed = product.materialize_and_persist_threads(
        org_node_ids=["engineering"],
        organization_tree=state["organization_tree"],
        worker_records=state["worker_records"],
        home=tmp_path,
    )

    assert changed[0]["status"] == "archived"
    assert changed[0]["read_only"] is True
    persisted = product.load_management_state(home=tmp_path)["threads"][0]
    assert persisted["status"] == "archived"
    assert persisted["read_only"] is True
