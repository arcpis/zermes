# Natural Language To Command Flow

Use this process to convert a natural-language staffing request into WorkerAgent commands.

## 1. Extract The Tree

Identify:

- Root requested worker or department.
- Direct children.
- Nested children.
- Responsibilities.
- Existing parent node.
- Actor requesting the change.

Examples of equivalent terms:

- employee, worker, agent, sub-agent, staff member -> WorkerAgent.
- subordinate, reports to, under, child -> child organization node.
- responsible for, owns, handles -> responsibility summary.
- department, team, group -> organization node; may require multiple workers depending on wording.

## 2. Normalize IDs

Use lowercase kebab-case ids. Prefer stable English role names.

Examples:

- 代码实现 -> `code-implementation`
- 前端实现 -> `frontend-implementation`
- 后端实现 -> `backend-implementation`
- Web 界面 -> `web-interface`
- App -> `app-client`
- 微信小程序 -> `wechat-mini-program`
- 测试 -> `quality-assurance`
- 运维 -> `operations`

Rules:

- Keep ids short and responsibility-based.
- Do not include stage numbers, implementation plan names, or temporary wording.
- If the user gives a desired id, use it if it is valid.
- If names collide with existing workers, ask whether to reuse, rename, or create a suffixed id.

## 3. Split Into Waves

Create a parent before its children.

For this tree:

```text
code-implementation
├─ frontend-implementation
│  ├─ web-interface
│  ├─ app-client
│  └─ wechat-mini-program
└─ backend-implementation
```

Use:

- Wave 1: `code-implementation` under an existing parent node.
- Wave 2: `frontend-implementation`, `backend-implementation` under `code-implementation`.
- Wave 3: `web-interface`, `app-client`, `wechat-mini-program` under `frontend-implementation`.

Do not emit child creation as immediately executable until parent creation has been approved and executed.

## 4. Generate Commands

For every new WorkerAgent, generate one `create_child_agent` draft command.

Template:

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor <actor-id> \
  --target-node <parent-node-id> \
  --requested-worker <new-worker-id> \
  --reason "<display name and responsibility>" \
  --json
```

Use `<existing-parent-node>` placeholders when the parent is unknown.

## 5. Decide Whether To Ask Before Commands

Ask a concise question before final commands when:

- The existing parent node is unknown.
- The actor id is unknown and the command must be runnable immediately.
- The request may create a worker under a node that does not exist yet.
- The user asks for destructive changes without naming asset disposition or rollback references.
- The same requested id may already exist.

If only minor naming choices are missing, choose reasonable ids and state assumptions.

## 6. Explain The Difference Between Draft And Creation

Always say:

- Draft commands create proposal validation output.
- Approval is required before execution.
- Execution is separate from draft generation.
- A child cannot be attached to a parent until that parent exists in active organization state.

## 7. Produce Verification Commands

After each wave:

```bash
zermes worker-agents evolution --json
zermes worker-agents approvals --json
zermes worker-agents organization --json
```

After execution:

```bash
zermes worker-agents workers --json
zermes worker-agents chats --json
```

Use these to confirm workers, nodes, and chat boundaries are visible.

