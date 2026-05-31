# Worker Agent Department Memory

Department memory stores long-lived, low-sensitive department knowledge under the active Hermes profile home:

```text
<hermes_home>/worker_agents/organization/departments/<department_id>/memory/
  proposals/
  accepted/
  history/
```

The store keeps proposals, active memories, and historical revisions separate. A proposal is only a review candidate. It never becomes active memory until `DepartmentMemoryReviewService` approves it.

## Invariants

- Department memory proposals are pending by default.
- Active department memories are written only by the review service.
- Rejected, expired, pending, or superseded proposals are not returned by department memory reads.
- Worker private memory text, full transcripts, secrets, credentials, raw adapter output, raw stdout, and raw stderr are rejected at the department memory boundary.
- Private worker assets can only enter this flow through low-sensitive proposal input summaries and references.
- Child departments inherit only explicitly inheritable or organization-level summaries from parent departments.
- Context injection must consume `DepartmentMemoryView` records from `DepartmentMemoryReadService`, not raw accepted memory JSON.

## Proposal Flow

Runtime result routing and private asset sharing can produce low-sensitive department memory candidates. `DepartmentMemoryProposalStore` persists those candidates in `memory/proposals/` and keeps them in `pending` state.

The store records source actor, source refs, candidate summary, rationale, sensitivity, review requirement, and source hash. A pending proposal with the same department, kind, and source hash is treated as an existing duplicate instead of silently overwriting the first proposal.

## Review Flow

`DepartmentMemoryReviewService` handles review decisions:

- `approve` writes an active `DepartmentMemoryRecord` to `memory/accepted/`.
- `reject`, `request_changes`, and `expire` only update proposal state.
- `approve` with `supersede_memory_id` writes the old active revision to `memory/history/<memory_id>/` and replaces the accepted memory with a higher revision.
- Restricted or user-confirmation-required proposals require a user confirmation reference before approval.

Main Agent review is not the same thing as user confirmation. Sensitive department memory still needs a user confirmation reference when the sensitivity requires it.

## Read Flow

`DepartmentMemoryReadService` returns redacted `DepartmentMemoryView` records. Reads can filter by kind, sensitivity, source ref, and inherited departments.

Restricted memories without permission references return an audit-safe placeholder instead of the stored summary. Inherited reads only return parent memories marked as inheritable summaries or organization summaries.

This module does not inject memories into runtime prompts. Context selection and prompt injection belong to the later context injection policy layer.
## Asset Review Console Projection

Department asset review UI models are defined in `worker_agents.management`.
They present proposal summaries, target departments, sensitivity, reviewer,
conflict refs, redaction requirements, and source refs without reading private
memory bodies or writing accepted assets directly.

The detail views for memory, skill, and tool policy proposals produce controlled
action requests for the underlying department asset services. Adoption history
rows link accepted, rejected, partial, archived, and expired decisions back to
proposal ids and low-sensitive source refs.
