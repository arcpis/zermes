# 代码自我进化架构参考

## 模块总览

代码自我进化由 `code_modification/` 包实现，工具入口在 `tools/code_modification_tool.py`，属于 `code_modification` 工具集。

```
code_modification/
  governance.py     任务 ID、分支命名、审计布局、安全策略常量
  approval.py       审批计划生成和文档写入
  git_workflow.py   安全 git 操作（分支、提交、合并）
  executor.py       批准后的任务状态、提交、合并
  verifier.py       验证计划、命令执行、安全审查
  thinking.py       只读思考：候选生成和定时思考
  token_strategy.py 低 token 分析上下文构建
  repo_lock.py      仓库级互斥锁
  self_update.py    自更新应用状态管理
  runtime_update.py 运行时发布版本状态管理
```

## 治理策略 (Governance)

**代码：** `code_modification.governance`

### 命名规则

- 任务 ID：`task-<hash>` 格式，从需求文本生成
- 开发分支：`self-evolution/dev/<task_id>`
- 集成分支：`self-evolution/main`

### 安全策略

`GovernancePolicy` 强制以下规则：

- 必须用户审批后才能修改代码
- 必须小步提交
- 必须详细的提交信息
- 禁止自动合并到 main

策略验证返回违规列表，空列表表示策略有效。

### 审计布局

`TaskRecordLayout` 为每个任务定义审计文件路径：

```
self-evolution/tasks/<task_id>/
  plan.md
  approval.md
  change-log.md
  execution-state.json
  verification.md
  verification-state.json
  final-report.md
```

### 工作区解析

`get_evolution_workspace()` 解析审计工作区路径。`resolve_self_evolution_project_root()` 解析可编辑的源码仓库路径，拒绝将运行时发布副本当作开发仓库。

## 审批流程 (Approval)

**代码：** `code_modification.approval`

`build_approval_plan()` 从自然语言需求生成 `ApprovalPlan`，包含：

- 需求摘要、影响范围、实施方案
- 风险评估、测试计划、待确认问题
- `recommend_execution`：无待确认问题时为 True
- 开发分支名称

`write_approval_documents()` 将计划写入审计文件。**此步骤绝不修改产品代码或创建分支。**

## 执行流程 (Executor)

**代码：** `code_modification.executor`

### 状态

`ExecutionState` 记录任务执行状态：task_id、status、分支信息、提交记录、计划步骤。

### 关键操作

- `start_approved_task()`：验证审批记录 → 获取仓库锁 → 创建/切换开发分支 → 写入执行状态
- `commit_task_step()`：只提交明确指定的文件列表 → 追加变更日志 → 更新执行状态
- `finalize_task_branch()`：验证所有步骤完成 → 合并到集成分支 → 释放仓库锁 → 写入最终报告

### 约束

- 必须存在审批记录才能启动
- 必须提供明确的审批文本
- 禁止 `git add .`，只允许显式文件列表
- 仓库锁确保同一时间只有一个任务操作同一仓库

## Git 工作流 (Git Workflow)

**代码：** `code_modification.git_workflow`

安全 git 操作封装：

- `require_git_repository()`：验证路径是 git 仓库根目录
- `require_clean_worktree()`：要求工作树干净
- `create_or_switch_development_branch()`：分支名必须在 `self-evolution/dev/` 命名空间下
- `commit_explicit_files()`：只暂存和提交指定的文件
- `merge_development_branch()`：合并开发分支到目标分支

所有 git 操作使用 `subprocess.run([...], shell=False)` 的 argv 形式。

## 验证流程 (Verifier)

**代码：** `code_modification.verifier`

### 验证命令

`VerificationCommand` 定义一个验证命令：命令行、目的、是否必须、超时时间。

`build_verification_commands()` 根据影响范围和已提交文件生成验证命令，只使用允许列表中的命令模式。

### 关键操作

- `plan_task_verification()`：生成验证计划
- `run_task_verification()`：执行验证命令，记录结果
- `record_task_safety_review()`：记录安全审查结果

验证命令是故意限制的，`verifier.py` 不是通用终端运行器。

## 思考模块 (Thinking)

**代码：** `code_modification.thinking`

只读的代码库分析，可以发现改进候选但**绝不修改代码**。

### 操作

- `status`：查看思考状态
- `enable`：启用定期自动思考
- `disable`：禁用定期自动思考
- `run_once`：手动触发一次思考

### 候选

`ImprovementCandidate` 包含：标题、摘要、证据、影响范围、风险等级、建议下一步、建议需求文本、测试想法。

### 配置

`ThinkingConfig`：启用状态、调度频率（默认每 7 天）、最大候选数（默认 5）、是否包含最近会话/测试失败/git 历史。

思考候选只是建议，必须回到 `complete_code_task` 流程才能实施。

## 分析上下文 (Token Strategy)

**代码：** `code_modification.token_strategy`

`build_analysis_context()` 在 token 预算内构建紧凑的仓库分析上下文：

- 扫描核心源文件和文档
- 根据需求关键词和显式路径优先排序
- 缓存已读取的文件摘要
- 输出上下文状态路径和任务摘要路径

`AnalysisBudget` 控制源文件数、摘要数、详细片段数、总字符数等限制。

## 仓库锁 (Repo Lock)

**代码：** `code_modification.repo_lock`

仓库级互斥锁，确保同一时间只有一个自我进化任务操作同一 git 仓库。

- `acquire_repo_lock()`：获取锁，记录 task_id、分支名、PID、主机名
- `release_repo_lock()`：释放锁
- `heartbeat_repo_lock()`：更新锁的心跳时间
- `force_release_repo_lock()`：强制释放（需审批文本和原因）
- `repo_lock_status()`：查询锁状态

锁信息存储在 `self-evolution/locks/repositories/<repo_key>/` 下。

## 自更新 (Self Update)

**代码：** `code_modification.self_update`

管理自我进化任务集成后的自更新应用状态。

### 状态流转

`plan` → `prepare` → `record_build` → `record_health` → `activate` / `rollback`

### 操作

- `plan`：规划更新（候选提交、前一个活跃提交、模式）
- `prepare`：准备更新（需审批文本）
- `record_build`：记录构建结果
- `record_health`：记录健康检查结果
- `activate`：激活更新（需审批文本）
- `rollback`：回滚更新（需审批文本和原因）

此模块只管理状态，不重启进程、不安装依赖、不运行构建命令。

## 运行时更新 (Runtime Update)

**代码：** `code_modification.runtime_update`

管理安装前缀下的运行时发布版本状态。

### 路径结构

```
<prefix>/runtime/
  active.json          当前活跃版本
  previous.json        前一个版本
  update-state.json    更新状态
  update.lock          更新锁
  restart-intent.json  重启意图
  candidates/          候选版本
  releases/            发布版本
```

### 关键操作

- `prepare_candidate_source()`：准备候选版本源码
- `prepare_candidate_environment()`：准备候选版本环境
- `run_candidate_health_checks()`：运行健康检查
- `promote_candidate_to_release()`：将候选提升为发布版本
- `activate_runtime_release()`：激活发布版本
- `rollback_active_release()`：回滚活跃版本
- `request_runtime_restart()`：请求运行时重启

此模块只管理版本指针和状态文件，不复制源码、不创建虚拟环境、不安装依赖。
