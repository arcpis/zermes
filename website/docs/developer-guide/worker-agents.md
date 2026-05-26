---
sidebar_position: 8
title: "Managed Worker Agents"
description: "Zermes WorkerAgent backend contracts, runtime boundaries, organization assets, and management read models"
---

# Managed Worker Agents

Zermes includes a backend contract layer for long-lived, governed worker identities. A `WorkerAgent` is a durable professional agent with a profile, lifecycle state, permissions, task records, memory and skill boundaries, organization placement, and runtime adapter configuration.

This system is different from the existing `delegate_task` path. `delegate_task` creates temporary child agents for short, isolated execution. `worker_agents/` models persistent employees and the governance surfaces around them.

## Package Map

The implementation lives under `worker_agents/`:

```text
worker_agents/
  profile.py                         # WorkerAgent profile contract
  registry.py, registry_service.py    # lifecycle registry and service API
  task_state.py, task_service.py       # runtime task state and events
  retention.py, cleanup.py            # retention policy and cleanup planning
  message_router.py                   # user-present chat routing
  department_chats.py                 # department chat binding and summaries
  organization.py                     # organization tree contract
  organization_evolution.py           # evolution proposal and approval policy
  organization_evolution_executor.py  # controlled execution records
  organization_memory_merge.py        # department memory merge classification
  organization_asset_disposition.py   # skill/tool asset disposition planning
  department_memory.py                # department memory proposals and reads
  department_skills.py                # department skill bindings and guardrails
  department_tool_policies.py         # department tool policies and approvals
  department_context_*.py             # minimal runtime context injection
  runtime_boundary.py                 # role/persona/session boundary
  runtime_contract.py                 # runtime request/event/result schema
  runtime_resources.py                # budget, cancellation, concurrency, transcripts
  internal_runtime_*.py               # native WorkerAgent runtime preparation
  external_adapters.py                # external adapter declarations
  external_adapter_runner.py          # external adapter run facade
  external_adapter_output.py          # external output normalization
  temporary_subagents*.py             # task-scoped child agent policy and runs
  result_routing.py                   # message/proposal/approval routing
  management/                         # dashboard, approval, review, import/export read models
  storage/                            # profile-home and install-data storage helpers
```

## Storage Boundary

WorkerAgent data is split by retention requirements:

- Long-term assets live under the profile home through `worker_agents/storage/paths.py`, anchored at `<zermes_home>/worker_agents/`.
- Runtime data lives under the install-local data directory, anchored at `<install_prefix>/data/worker_agents/`.

Long-term assets include registry records, worker profiles, organization trees, department assets, proposal/history summaries, audit summaries, and retained manifests. Runtime data includes task state, transcripts, logs, external stdout/stderr references, temporary plans, adapter caches, and task-scoped temporary subagent data.

Deleting runtime `data/worker_agents/` must not delete worker identity, organization structure, accepted department assets, or retained audit summaries.

## Runtime Boundary

WorkerAgent execution flows through minimal contracts:

1. A task service records an enabled worker task and its lifecycle.
2. Runtime context builders derive a minimal `RuntimeRequestContext` from worker, task, permission, budget, and department context summaries.
3. The shared runtime boundary validates `AgentRuntimeSessionConfig`; it rejects wildcard permissions, raw private memory, full transcripts, credentials, and budget expansion.
4. Internal or external runtime adapters produce low-sensitivity events and terminal results.
5. Task integration and result routing convert events/results into task records, user-visible messages, proposals, manifests, or approval requests.

The runtime layer does not directly write private memory, accepted department assets, or organization structure. Those changes go through proposal, review, or executor-specific services.

## Organization And Assets

The organization layer sits above worker profiles and registry state. It adds:

- `OrgTree` and `OrgNode` contracts for departments, teams, owners, members, lifecycle state, and summary views.
- Department chat bindings that keep user-present chat threads explicit and avoid single-member department group chats.
- Department memory, skill, and tool policy stores with proposal/review workflows.
- Context selection and rendering that inject only accepted, relevant, redacted department assets.
- Memory merge, skill disposition, and tool policy disposition planners for organization changes.

Organization evolution is proposal-first. Creation, deletion, merge, archive, asset migration, permission expansion, external agent changes, and sensitive memory movement must be represented as proposals with risk and approval requirements before execution.

## Management Models

`worker_agents/management/` provides low-sensitivity read models and controlled request builders for dashboards and operations surfaces:

- Worker and organization dashboard summaries.
- Chat/routing console summaries.
- Approval queue and approval action audit records.
- Asset review items and adoption history.
- Evolution proposal workbench, wizard draft builders, and execution report views.
- Import/export package validation and retention cleanup planning.

These modules are not a frontend and are not execution shortcuts. They should not mutate the active organization tree, bypass approval policy, read raw transcripts, or expose credentials and private memory contents.

## Product Entrypoints

`hermes_cli/worker_agents_product.py` is the shared adapter used by the CLI and dashboard API. It loads the active profile's low-sensitivity management state, builds existing `worker_agents.management` DTOs, and appends controlled message envelopes under `worker_agents/threads/<thread_id>/messages.jsonl`.

CLI registration lives in `hermes_cli/worker_agents_cmd.py` and is exposed as `hermes worker-agents`. Dashboard registration lives in `hermes_cli/worker_agents_api.py` under `/api/worker-agents/*`, then `hermes_cli/web_server.py` mounts the router behind the existing dashboard session token and Host-header protections.

The dashboard page is `web/src/pages/WorkerAgentsPage.tsx`, routed at `/worker-agents`.

Department chat visibility is materialized in the product adapter from the
low-sensitivity organization tree and worker management records. Active
departments or teams with at least two enabled workers get a managed department
thread summary. Single-worker departments remain in `private_or_parent_chat`
mode and should offer a direct worker chat or parent chat path instead.

Direct worker chats are opened through `ensure_direct_worker_chat` and
`POST /api/worker-agents/workers/{worker_id}/direct-chat`. That path validates
the worker status and creates or reuses a direct thread summary; it does not
change worker profiles, registry state, organization structure, or permissions.

These entrypoints must stay thin:

- Use management DTO serializers such as `dashboard_snapshot_to_dict`, `worker_management_list_item_to_dict`, and related action request serializers.
- Keep chat history scoped by `thread_id`.
- Send messages through `MessageRouter` validation before writing controlled envelopes.
- Do not read or reconstruct runtime raw transcripts.
- Do not turn dashboard APIs into file browsers or executors.
- Do not directly edit active organization trees, registry records, department active assets, tool policies, or retention deletions.

## Temporary Subagents

WorkerAgents can request temporary subagents only inside the parent's effective policy. The policy checks model, tool, workspace, token/cost budget, timeout, and concurrency boundaries. A temporary subagent can return a result envelope to its parent task, but it cannot create a long-term worker profile, registry entry, private memory, or chat thread.

## Tests

Run the focused WorkerAgent suite from the repository root:

```bash
venv/bin/python -m pytest tests/worker_agents -q
```

The full suite covers profile and registry contracts, task state, cleanup, message routing, organization evolution, runtime adapters, department assets, management read models, import/export planning, and result routing.
