# Worker Agent Architecture Reference

This document consolidates the internal architecture contracts for the Worker Agent subsystem. All modules live under `worker_agents/` in the codebase.

## Storage Boundaries

Worker agents use two storage roots:

| Root | Path | Lifetime | Contents |
|------|------|----------|----------|
| Profile home | `<zermes_home>/worker_agents/` | Durable | Registry, profiles, organization, threads, manifests, shared policy |
| Install data | `<install_dir>/data/worker_agents/` | Clearable | Task runtime, events, transcripts, caches, logs, cleanup runs |

Deleting `data/` must never delete worker identity, memory, skill bindings, manifests, or audit summaries. Use `worker_agents.storage` for path helpers instead of manual path joining.

## Profiles

**Code:** `worker_agents.profile`, `worker_agents.storage.profile_store`

Each worker has a durable profile at `<zermes_home>/worker_agents/workers/<worker_id>/worker.json`.

Required fields: `worker_id`, `schema_version`, `display_name`, `description`, `role`.

Policy fields: `responsibilities`, `runtime`, `memory`, `skills`, `tools`, `workspace`, `communication`, `model`, `budgets`, `limits`, `cost_policy`, `delegation`, `metadata`.

Defaults are conservative: no tools, no workspace writes, no chat, no delegation, zero budget. Capability must be explicitly granted.

```python
store = WorkerAgentProfileStore()
profile = store.create_default_worker_profile("researcher", display_name="Researcher",
    description="Finds and summarizes information.", role="research")
store.save_worker_profile(profile)
```

## Registry

**Code:** `worker_agents.registry`, `worker_agents.registry_service`

Lightweight lifecycle index at `<zermes_home>/worker_agents/registry.json`. Stores id, display name, role, runtime type, status, profile path, tags, timestamps.

Lifecycle states: `registered` → `enabled` → `disabled` → `archived` → `deleted`. Archived workers must go through `disabled` before re-enabling. Deletion is soft by default.

```python
service = WorkerRegistryService(WorkerAgentProfileStore())
record = service.register_worker(worker_id="researcher", display_name="Researcher",
    description="Finds and summarizes information.", role="research")
service.enable_worker(record.worker_id, updated_by="main-agent")
```

## Tasks

**Code:** `worker_agents.task_state`, `worker_agents.task_service`, `worker_agents.storage.task_store`

Clearable runtime data under `<install_dir>/data/worker_agents/tasks/<task_id>/`.

Files: `state.json`, `events.jsonl`, `requests.jsonl`, `rolling-summary.md`, `result.json`, `artifacts/`.

Lifecycle: `draft` → `queued` → `running` → `waiting_for_input` / `waiting_for_approval` → `succeeded` / `failed` / `cancelled` / `expired`. Terminal states are not restartable.

Only `enabled` workers can receive new tasks. The service does not start adapters or execute work.

## Organization

**Code:** `worker_agents.organization`, `worker_agents.storage.organization_store`, `worker_agents.organization_evolution`, `worker_agents.organization_evolution_executor`

### Nodes

`OrgNode` types: `root`, `department`, `team`, `individual`. Leaders are `main_agent`, `worker`, or `none`. Workers are referenced by id only.

`OrgTree` stores a validated snapshot with one root, node records keyed by id, and a revision for concurrency.

### Evolution Proposals

Proposal types: `create_child_agent`, `delete_child_agent`, `merge_department`, `transfer_assets`, `archive_org_node`.

Risk policy: permission expansion, budget/model increase, external agent involvement, and sensitive memory movement require user approval. Active tasks and pending high-risk approvals are blockers.

Approved proposals are executed through `organization_evolution_executor`, which is the controlled write boundary for active tree updates, registry lifecycle changes, and chat binding status markers.

### Durable Store

```
<zermes_home>/worker_agents/organization/
  active.json
  proposals/<proposal_id>.json
  history/<change_id>.json
```

## Message Router

**Code:** `worker_agents.message_router`, `worker_agents.message_mentions`, `worker_agents.message_broadcasts`, `worker_agents.message_followups`

### Threads

Thread types: `direct` (user + one worker), `organization_group` (user + main agent + workers/org nodes), `project_group` (user + main agent + project participants).

All threads must include exactly one user. Direct threads include exactly one worker and are main-agent visible. Group threads must include the main agent.

### Mentions

Directed responsibility signals. Targets can be workers, departments, teams, or org nodes. Department/team mentions route to the worker leader by default.

Delivery states: pending, seen, public_replied, silent_acknowledged, no_response_needed, rejected, delegated, deferred, internal_todo, timed_out, failed.

### Broadcasts

Low-sensitivity context synchronization. Default routing is conservative: department/team/org-node broadcasts route to the worker leader.

Delivery states: delivered, seen, handled, ignored, failed.

### Follow-Ups

`apply_mention_timeouts` marks eligible open mentions as timed out. `summarize_delivery_followups` returns items for main-agent review. Timeouts are idempotent and do not send reminders.

## Department Chats

**Code:** `worker_agents.department_chats`

Binding types: `department_default`, `team_default`, `project`. Every department/team chat must include the user and main agent.

Single-worker departments do not get their own group chat; they fall back to a direct thread or parent group thread.

Hierarchical summaries are the only upward context boundary. Parent chats receive summaries, decisions, and deliverable references — not full child transcripts.

## Department Memory

**Code:** `worker_agents.department_memory`

Storage: `<hermes_home>/worker_agents/organization/departments/<department_id>/memory/` with `proposals/`, `accepted/`, `history/`.

Proposals are pending by default and only become active through `DepartmentMemoryReviewService`. Restricted memories require user confirmation. Inherited reads only return parent memories marked as inheritable or organization summaries.

## Department Skills

**Code:** `worker_agents.department_skills`

Storage: `worker_agents/organization/departments/<department_id>/skills/` with `proposals/`, `active/`, `history/`.

Binding states: `recommended`, `default`, `restricted`, `deprecated`, `disabled`. Department defaults never modify worker profiles or grant tools/workspace/budget.

Only `inheritable_guidance` and `organization_guidance` can be inherited. Conflict resolution is conservative: disabled/deprecated/restricted wins over default/recommended.

## Department Tool Policies

**Code:** `worker_agents.department_tool_policies`

Storage: `worker_agents/organization/departments/<department_id>/policies/tools/`.

Policy resolution: `deny` wins over `allow`. Child departments can tighten but cannot relax inherited policy without approved reference. `cross_check_department_tool_policy_with_worker` intersects department policy with worker profile — department allow + worker allow = effective allow; any deny stays denied.

## Department Context Injection

**Code:** `worker_agents.department_context_bundle`, `worker_agents.department_context_selection`, `worker_agents.department_context_builder`, `worker_agents.department_context_rendering`

The final summary-only boundary between accepted department assets and a worker runtime session. Pipeline: selection → builder (applies limits) → rendering → optional `AgentRuntimeSessionConfig.department_context`.

Prohibited inputs: full transcripts, private memory, unaccepted proposals, secrets/credentials, complete department records when redacted views exist.

## Runtime Boundary

**Code:** `worker_agents.runtime_boundary`, `worker_agents.runtime_facade`

### Roles

- `main_agent`: governed user entry point
- `managed_worker`: durable WorkerAgent task identity, must bind `worker_id`
- `temporary_child`: short-lived child task, must bind parent ids, cannot bind durable `worker_id`

### Session Config

`AgentRuntimeSessionConfig` groups: `RuntimeProfileSummary`, `RuntimePermissionSnapshot`, `RuntimeBudgetSnapshot`, `RuntimeContextBundle`. Budgets are immutable snapshots — sessions may receive less but never more than the ceiling.

```python
invocation = SharedAgentRuntimeFacade().prepare_invocation(session_config)
```

## Internal Runtime

**Code:** `worker_agents.internal_runtime_context`, `worker_agents.internal_runtime_runner`, `worker_agents.internal_runtime_task_integration`

Connects durable WorkerAgent records and WorkerTask state to the shared runtime facade. The runner prepares a `RuntimeRequest` with `runtime_type=internal_worker` and passes it to `SharedAgentRuntimeFacade`.

Task state integration: `mark_internal_runtime_started`, `record_internal_runtime_event`, `finalize_internal_runtime_result`. Cancellation and timeout map to the existing task lifecycle.

## External Adapters

**Code:** `worker_agents.external_adapters`, `worker_agents.external_adapter_runner`, `worker_agents.external_adapter_output`

Non-native execution backends. `ExternalAdapterDefinition` declares capabilities before startup. The runner uses a narrow backend protocol: `health_check()`, `start()`, `cancel()`, `poll()`. Output is normalized into `RuntimeResult` through `normalize_external_adapter_output()`.

Raw adapter output stays in clearable install-data as middle-data references. Long-term assets receive only retained manifest refs and low-sensitive summaries.

## Runtime Resource Controls

**Code:** `worker_agents.runtime_resources`

- **Budget**: `resolve_runtime_budget()` applies the strictest value from all layers (worker profile, org policy, task request, parent runtime, adapter definition, system defaults).
- **Cancellation/Timeout**: `RuntimeCancellationToken` records the first request; `RuntimeDeadline` uses monotonic clock.
- **Concurrency**: `RuntimeConcurrencyGate` is in-process only. Dimensions: user, org node, worker, adapter, runtime type, parent session.
- **Transcript**: `RuntimeTranscriptSink` writes only under task storage, returns refs. Raw transcript is clearable middle data.

## Private Assets

**Code:** `worker_agents.private_assets`, `worker_agents.private_skill_experience`, `worker_agents.tool_permission_snapshot`

Private memory belongs to exactly one worker. `PrivateAssetProposalInput` and `SkillExperienceProposalInput` are reviewable inputs for department proposals — they carry only low-sensitivity summaries, source refs, and sensitivity labels.

`WorkerToolPermissionSnapshot` is a credential-free view of worker profile tool permissions for department policy cross-checking.

## Temporary Subagents

**Code:** `worker_agents.temporary_subagents`, `worker_agents.temporary_subagent_policy`, `worker_agents.temporary_subagent_runner`

Task-scoped runtime sessions created by a managed WorkerAgent. Not durable — no registry entry, no profile, no private memory, no department membership.

Delegation policy: requested tools must be subset of parent tools, model must be allowed, workspace roots must stay inside parent policy, budgets within parent limits.

Three execution paths: shared runtime facade, external adapter runner, delegate-task adapter protocol.

## Retention and Cleanup

**Code:** `worker_agents.retention`, `worker_agents.cleanup`, `worker_agents.manifests`

Policy at `<zermes_home>/worker_agents/shared/retention-policy.json`. Default keeps active tasks and protected data forever, allows short-window cleanup for caches/logs/transcripts.

`CleanupPlanner` scans only install data and creates dry-run plans. `CleanupExecutor` validates before deleting. `TaskResultRetentionService` promotes manifest and audit candidates from task results into durable profile storage.

Memory and learning candidates remain candidates — they are not written to long-term memory by the retention service.

## Global Safety Boundaries

The following rules apply across all worker-agent modules:

- No module reads raw transcripts, private memory text, credentials, secrets, tokens, or raw adapter output except where explicitly required for that module's single responsibility.
- No module writes to worker profiles, registry, organization tree, or department assets outside its designated controlled executor.
- Summaries and refs are the standard cross-layer data format. Full content stays within its owning module.
- Department policy never expands worker profile permissions.
- All cross-module proposals go through review/approval before becoming active.
