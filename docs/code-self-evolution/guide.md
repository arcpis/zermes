# 代码自我进化使用指南

## 什么是代码自我进化

代码自我进化是 Zermes 的安全代码修改能力。它允许你通过与主 Agent 对话，让 Zermes 修改自己的代码——修复 bug、添加功能、重构模块等。整个过程受严格的审批和验证流程保护，确保每一步都在你的掌控之中。

核心原则：**先规划，后审批，再执行，最后验证。** 主 Agent 不会在未经你批准的情况下修改任何产品代码。

## 如何启用

代码自我进化工具属于 `code_modification` 工具集，默认已包含在主 Agent 的工具列表中。你只需要在对话中提出代码修改需求，主 Agent 就会自动启动自我进化流程。

## 完整工作流

```
用户提出需求 → 生成审批计划 → 用户审批 → 创建开发分支 → 逐步提交修改 → 验证 → 安全审查 → 合并
```

### 第一步：提出需求

直接用自然语言告诉主 Agent 你想修改什么。

```
用户：把工具注册的日志级别从 INFO 改成 DEBUG，方便调试。
```

主 Agent 会调用 `complete_code_task` 生成一个审批计划，包含：

- 需求摘要
- 影响范围分析
- 实施方案
- 风险评估
- 测试计划
- 待确认问题

计划生成后，**不会修改任何代码**。

### 第二步：审批

审查主 Agent 生成的计划，确认无误后给出审批。

```
用户：计划看起来没问题，批准执行。

主 Agent：收到审批，创建开发分支 self-evolution/dev/<task_id> 并开始实施。
→ 调用 start_approved_code_task(task_id, approval_text="用户批准执行")
```

### 第三步：逐步实施

主 Agent 会在开发分支上逐步提交修改，每一步只提交明确的文件列表（禁止 `git add .`）。

```
主 Agent：第一步修改完成，提交了 tools/registry.py。
→ 调用 commit_code_task_step(task_id, summary="将工具注册日志级别改为 DEBUG", files=["tools/registry.py"])
```

### 第四步：验证

修改完成后，主 Agent 会运行验证命令确认代码正确。

```
主 Agent：开始验证修改。
→ 调用 plan_code_task_verification(task_id)
→ 调用 run_code_task_verification(task_id)
```

### 第五步：安全审查

对修改进行安全审查，确认没有引入风险。

```
主 Agent：进行安全审查。
→ 调用 record_code_task_safety_review(task_id, questions=["是否修改了权限相关代码？"], answers=["否"], conclusion="安全")
```

### 第六步：合并

验证和安全审查通过后，将开发分支合并到集成分支。

```
主 Agent：验证通过，合并到 self-evolution/main。
→ 调用 finalize_code_task_branch(task_id)
```

## 使用实例

### 实例一：修复 Bug

```
用户：修改你的代码，hermes_cli/commands.py 里的 /help 命令在 Windows 上显示乱码，帮我修一下。

主 Agent：我来分析这个问题并生成修改计划。
→ 调用 complete_code_task(requirement="修复 /help 命令在 Windows 上的乱码问题",
                       affected_areas=["hermes_cli/commands.py"])
→ 返回审批计划，task_id: task-abc123

用户：批准，问题确实存在，按计划修改。

主 Agent：
→ 调用 start_approved_code_task(task_id="task-abc123", approval_text="用户确认 bug 存在，批准修复")
→ 调用 commit_code_task_step(task_id="task-abc123", summary="修复 Windows 编码问题",
                            files=["hermes_cli/commands.py"])
→ 调用 run_code_task_verification(task_id="task-abc123")
→ 调用 record_code_task_safety_review(task_id="task-abc123",
    questions=["是否影响非 Windows 平台？"], answers=["否，仅修改 Windows 分支"], conclusion="安全")
→ 调用 finalize_code_task_branch(task_id="task-abc123")
→ 修复完成，已合并到 self-evolution/main
```

### 实例二：添加新功能

```
用户：修改你的代码，给 Worker Agent 的消息工具加一个消息优先级字段，支持 high/normal/low。

主 Agent：
→ 调用 complete_code_task(requirement="为 Worker Agent 消息工具添加优先级字段",
                       affected_areas=["tools/worker_messaging_tool.py", "worker_agents/message_router.py"])
→ 返回审批计划，列出影响范围和实施方案

用户：计划可以，但优先级默认值应该是 normal 而不是 low。

主 Agent：收到，按你的要求调整。
→ 调用 start_approved_code_task(task_id, approval_text="用户批准，优先级默认 normal")
→ 逐步提交修改...
→ 验证...
→ 合并...
```

### 实例三：让 Zermes 自主思考改进方向

除了被动接受需求，Zermes 还可以主动分析代码库，发现可改进之处。

```
用户：修改你的代码，想想有什么可以改进的。

主 Agent：
→ 调用 self_evolution_thinking(action="run_once")
→ 返回改进候选列表：
  1. [低风险] tools/registry.py 中的注册日志可以增加工具集名称
  2. [中风险] hermes_cli/commands.py 的帮助文本可以自动从 docstring 生成
  3. [低风险] worker_agents/message_router.py 的超时默认值可以配置化

用户：第 1 和第 3 个看起来不错，帮我实现。

主 Agent：
→ 调用 complete_code_task(requirement="实现思考候选 #1 和 #3")
→ ...后续流程同上
```

你也可以启用定期自动思考：

```
用户：开启自我进化思考，每周运行一次。

主 Agent：
→ 调用 self_evolution_thinking(action="enable", schedule="every 7d")
→ 已启用，Zermes 会每周自动分析代码库并生成改进候选
```

## 审计文件

每个自我进化任务在 `self-evolution/tasks/<task_id>/` 下生成审计文件：

```
plan.md              修改计划
approval.md          审批记录
change-log.md        变更日志
execution-state.json 执行状态
verification.md      验证记录
verification-state.json 验证状态
final-report.md      最终报告
```

## 安全保障

- **审批前置**：任何代码修改都必须经过用户明确审批
- **小步提交**：每一步只提交明确指定的文件，禁止 `git add .`
- **独立分支**：修改在 `self-evolution/dev/<task_id>` 分支上进行，不影响主分支
- **验证必过**：合并前必须通过验证命令
- **仓库锁**：同一时间只允许一个任务操作同一仓库
- **安全审查**：对修改进行独立的安全问题检查
- **禁止自动合并**：不会自动合并到 `main` 或 `master`
