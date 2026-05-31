# Worker Agent Private Assets

Worker private assets are durable records owned by one managed worker. They sit
between the worker profile contract and future department asset stores.

Private assets are implemented in:

- `worker_agents.private_assets`
- `worker_agents.private_skill_experience`
- `worker_agents.tool_permission_snapshot`

## Invariants

- Private memory belongs to exactly one worker.
- Private skill experience remains personal until it becomes an explicit proposal input.
- Tool permission snapshots are read-only views of the worker profile.
- Department assets consume low-sensitivity summaries, source references, hashes, and review requirements.
- Department assets must not directly read full private memory, full runtime transcripts, skill source, external raw logs, credentials, or secrets.
- Department tool policy cannot expand a worker profile's tools, workspace roots, token budget, cost budget, or high-risk permission state.

## Proposal Inputs

`PrivateAssetProposalInput` and `SkillExperienceProposalInput` are not accepted
department assets. They are reviewable inputs for later department memory or
department skill proposal stores.

They intentionally carry only:

- low-sensitivity summary text
- source references
- target scope
- sensitivity label
- review requirement
- optional hash or audit summary

Raw transcripts, private memory text, credential-like fields, raw stdout/stderr,
full prompts, skill source, and external adapter raw output are rejected before a
private asset can cross into proposal input.

## Tool Permission Snapshots

`WorkerToolPermissionSnapshot` is generated from `WorkerAgentProfile`. It is a
credential-free compatibility input for later department tool policy resolution.

The snapshot records allowed tools, tools requiring approval, workspace roots,
and budget ceilings. It does not grant tools and does not modify the profile.
Compatibility checks return explicit violation codes when a department or task
policy asks for tools, workspace access, or budget beyond the worker profile.

High-risk tools that already exist in the worker profile approval list return an
approval-required result instead of being silently allowed.
