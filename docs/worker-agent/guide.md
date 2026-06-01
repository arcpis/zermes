# Worker Agent 使用指南

## 什么是 Worker Agent

Worker Agent 是 Zermes 主 Agent 管理下的专职子 Agent。每个 Worker 有独立的身份、权限、工具集和预算，专注于特定领域（如编码、研究、设计）。主 Agent 通过群聊线程向 Worker 分发任务，Worker 处理后回复结果。

核心概念：

- **Worker**：一个专职 Agent，拥有独立的 profile（身份、权限、预算）
- **组织树**：部门/团队/个人的层级结构，决定 Worker 归属和协作关系
- **群聊线程**：主 Agent 与 Worker 之间的通信通道
- **任务分发**：主 Agent 通过 `@mention` 向 Worker 发送任务

## 创建 Worker Agent

通过自然语言与主 Agent 对话即可创建 Worker。主 Agent 会使用 `evolution-apply-draft` 工具在组织树中注册新 Worker。

### 示例：创建一个编码 Agent

```
用户：帮我创建一个叫 coder-agent 的 worker agent，负责代码编写和修改，并为其创建两个员工分别负责代码编写和测试。

主 Agent：好的，我来创建 coder-agent。
→ 调用 evolution-apply-draft(proposal_kind='create_child_agent', requested_worker='coder-agent')
→ 返回：coder-agent 已注册并启用
```

## 删除 Worker Agent

删除 Worker 通过组织演进提案完成。主 Agent 会先确认 Worker 没有活跃任务，然后执行删除。

### 示例：删除一个 Worker

```
用户：把 coder-agent 的 worker agent 删掉，暂时不需要了。

主 Agent：让我先检查 coder-agent 的状态……没有活跃任务，可以安全删除。
→ 调用 evolution-apply-draft(proposal_kind='delete_child_agent', target_node='coder-agent')
→ 返回：coder-agent 已标记为 deleted（软删除，数据保留）
```

## 分发任务给 Worker

主 Agent 通过 `send_worker_message` 工具向 Worker 发送任务消息，使用 `@mention` 指定目标 Worker。

### 示例：分发编码任务

```
用户：通过worker-agent分发需求，让 coder-agent 帮我写一个 Python 的快速排序函数。

主 Agent：我来把任务分发给 coder-agent。
→ 调用 send_worker_message(text="请编写一个 Python 快速排序函数，要求：\n1. 支持自定义比较函数\n2. 包含类型注解\n3. 添加基本的单元测试", mention_worker_ids=["coder-agent"])
→ 返回：任务已分发，task_id: task-abc123

用户：coder-agent 完成了吗？

主 Agent：让我检查一下回复。
→ 调用 check_worker_replies()
→ 返回：coder-agent 已回复，任务完成
```

## 查看状态

### 通过 Dashboard 查看（推荐）

打开 Dashboard 的 `Worker Agents` 页面，可以查看 Overview、Workers、Organization、Chats、Approvals 等标签页。

### 通过 CLI 查看

```bash
# 查看 Worker 总览
hermes worker-agents overview

# 查看所有 Worker 列表
hermes worker-agents workers

# 查看组织结构
hermes worker-agents organization

# 查看聊天记录
hermes worker-agents chats
hermes worker-agents chat-history thread-default-group --limit 20

# 查看待审批项
hermes worker-agents approvals
```
