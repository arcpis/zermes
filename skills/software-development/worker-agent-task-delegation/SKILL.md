---
name: worker-agent-task-delegation
description: "WorkerAgent task delegation workflow: split a user requirement, choose target workers, send worker messages, wait or check replies, and summarize results. Load for managed WorkerAgent demand dispatch, task distribution, cross-worker coordination, or feedback-loop closure."
license: MIT
metadata:
  hermes:
    tags: [worker-agents, delegation, task-dispatch, coordination]
    related_skills: [worker-agent]
---

# WorkerAgent Task Delegation

Use this skill when a user wants work distributed to managed Worker Agents. This is for task execution flow, not organization changes. Use `worker-agent` first only when workers, departments, or chat bindings must be created or changed before dispatch.

## Dispatch Flow

1. Inspect the current WorkerAgent organization and chats before dispatching.
2. Split the user requirement into independently verifiable sub-tasks.
3. Select target workers by responsibility, not by availability guesswork.
4. Send each sub-task with `send_worker_message`, using explicit `mention_worker_ids`.
5. For synchronous work, call `wait_for_worker_reply`; for asynchronous work, call `check_worker_replies` before reporting back.
6. Summarize completed worker outputs, pending work, blockers, and next actions for the user.

## Required Tools

Use these tools when available:

- `send_worker_message`: dispatch a task into the WorkerAgent group chat and mention target workers.
- `check_worker_replies`: read new Worker replies and update pending task state.
- `wait_for_worker_reply`: block for a Worker reply when the user needs an immediate answer.

If any required tool is unavailable, stop and report that WorkerAgent task delegation is not executable in the current toolset.

## Dispatch Rules

- Always mention explicit workers for multi-worker group chats. Do not rely on a normal untargeted group message to pick a worker.
- Make each sub-task self-contained: include the objective, relevant context, expected output, constraints, and where to report.
- Do not assign the same sub-task to multiple workers unless the user asks for redundant review.
- If a worker reply is a question or blocker, surface it instead of marking the task complete.
- Treat normal worker chatter as progress only when it clearly answers the dispatched task.
- Never claim a Worker completed work until `check_worker_replies` or `wait_for_worker_reply` has observed the completion.

## Synchronous Pattern

Use this when the user expects a single consolidated answer in the current turn.

```text
1. send_worker_message(text=<sub-task>, mention_worker_ids=[<worker-id>])
2. wait_for_worker_reply(worker_ids=[<worker-id>], timeout_seconds=<bounded timeout>)
3. Summarize the reply or timeout.
```

For multiple workers, dispatch all sub-tasks first, then wait/check for replies and produce one consolidated summary.

## Asynchronous Pattern

Use this when the work may outlive the current turn.

```text
1. send_worker_message(text=<sub-task>, mention_worker_ids=[<worker-id>])
2. Tell the user which tasks were dispatched and which workers own them.
3. On follow-up, run check_worker_replies before answering.
```

The final response must distinguish dispatched, completed, pending, and blocked work.

## When To Use WorkerAgent Organization Skill

Use `worker-agent` before this skill only when dispatch is blocked by missing structure:

- the target worker does not exist;
- department membership or chat binding is wrong;
- a worker profile needs a tool, budget, model, or permission change;
- the user asked to create, archive, merge, or rename workers/departments.

After the organization change is verified, return to this task delegation workflow.

## Output Checklist

Before replying to the user, include:

- workers targeted;
- tasks dispatched;
- replies received;
- blockers or timeouts;
- remaining pending tasks;
- concise final recommendation or next action.
