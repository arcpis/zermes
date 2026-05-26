<p align="center">
  <img src="assets/banner.png" alt="Zermes" width="100%">
</p>

# Zermes

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-English-lightgrey?style=for-the-badge" alt="English"></a>
  <a href="https://hermes-agent.nousresearch.com/docs/"><img src="https://img.shields.io/badge/Hermes%20Docs-hermes--agent.nousresearch.com-FFD700?style=for-the-badge" alt="Hermes 文档"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Hermes%20Community-Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Hermes 社区"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
</p>

Zermes 是基于 Hermes Agent 修改而来的 AI Agent 项目，重点面向有治理约束的代码级自我进化。它保留了 Hermes 实用的运行时基础：终端 AI Agent、可配置模型提供商、工具集、技能、记忆、定时任务和消息平台网关。在此基础上，Zermes 更强调以可审计、可审批、可验证的方式改进 Agent 自身仓库。

首选的用户命令是 `zermes`。为便于迁移，必要位置仍保留 Hermes 兼容名称和内部结构；新的 Zermes 安装建议使用 Zermes 源码运行时安装器以及面向 Zermes 的运行时布局。

## 特点

1. **代码级自我进化能力**

   功能点：Zermes 可把用户提出的功能需求、仓库改进建议或定时 self-evolution thinking 产生的候选项，转化为审批优先的实现计划，并在获得明确批准后进入专用任务分支修改自身代码。每一步代码变更都要求显式文件列表、变更记录、验证计划和验证结果。

   优势：它让 Agent 具备真实改进自身仓库的能力，同时把高风险环节控制在可见、可审查、可验证、可回退的流程中，避免把自我进化变成不可追踪的自动改写。

   适用场景：适合需要长期维护 Agent 能力、持续吸收改进建议、但又要求审批、审计和验证闭环的代码型 AI Agent 项目。

2. **受管 WorkerAgent 员工体系**

   功能点：Zermes 提供“员工式 Agent”的后端 contract 与 service 层。`WorkerAgent` 是长期存在的专业身份，可拥有独立 profile、生命周期状态、职责边界、权限、任务记录、runtime adapter、模型与预算策略、私有记忆边界、skill 使用策略和组织归属；员工私聊、部门群聊、项目群聊、`@` 提及、广播和组织树管理统一通过受管链路处理。

   优势：它把多 Agent 协作从临时、不可见的子 Agent 调用，提升为用户在场、权限清晰、上下文最小化、结果低敏化、资产 proposal-first 的组织化协作模式。内部 WorkerAgent 与外部编码、媒体生成、研究等 Agent 通过统一 runtime contract 和 adapter 接入，便于审计、交接、预算控制和治理扩展。

   适用场景：适合需要多角色长期协作、部门化任务分工、外部 Agent 接入、组织记忆沉淀和受控团队演化的 Agent 平台。目前该能力已覆盖后端契约与服务层，并配有 `tests/worker_agents` 专项测试；完整终端用户管理 UI 仍待交付。

## 安装和使用

### 推荐方式：源码运行时安装器

从默认 `main` 分支安装：

```bash
git clone https://github.com/arcpis/zerme.git
cd zermes
python3 install.py install --install-deps --global-command
```

在 Windows PowerShell 中，如果你的 Python 启动器是 `python`，可以使用：

```powershell
git clone https://github.com/arcpis/zerme.git
cd zermes
python install.py install --install-deps --global-command
```

安装器会创建一个受管理的运行时，而不是直接从可变的开发 checkout 中运行。它可以：

- 将选定源码复制到 `<prefix>/runtime/releases/<release-id>/`；
- 创建运行时虚拟环境；
- 在提供 `--install-deps` 时安装 Python 依赖；
- 在 `<prefix>/bin` 下创建启动器；
- 可选地为当前用户创建全局 `zermes` 命令；
- 将用户数据保存在独立的数据目录中。

常用安装选项：

```bash
python3 install.py install --dry-run
python3 install.py install --prefix ~/.local/share/zermes --data-dir ~/.zermes --install-deps --global-command
python3 install.py install --no-install-deps
python3 install.py install --no-global-command
```

安装后：

```bash
zermes
zermes setup
zermes model
zermes tools
zermes gateway
zermes doctor
```

### 更新

更新必须从明确的源码 checkout 构建。先拉取最新源码，再构建并激活更新候选版本：

```bash
cd zermes
git pull
python3 install.py update --current-source --install-deps --activate --restart
```

也可以从另一个 checkout 更新已安装运行时：

```bash
python3 install.py update --prefix <prefix> --source <source-dir> --install-deps --activate
```

常用更新选项：

```bash
python3 install.py update --current-source --no-activate
python3 install.py update --current-source --skip-verify
python3 install.py rollback --prefix <prefix>
```

`--no-activate` 会构建并验证候选版本，但不切换 `active.json`。`rollback` 会把运行时指回上一个 release，但不会删除 release 文件。

### 卸载

移除已安装的软件运行时，同时默认保留用户数据：

```bash
python3 install.py uninstall --prefix <prefix>
```

同时移除记录的数据目录和安装器创建的全局命令：

```bash
python3 install.py uninstall --prefix <prefix> --remove-data --remove-global-command
```

如果想先检查卸载意图，可以使用：

```bash
python3 install.py uninstall --prefix <prefix> --dry-run
```

### 开发 checkout

开发时仍然可以直接在源码 checkout 中工作：

```bash
git clone https://github.com/arcpis/zerme.git
cd zermes
python3 -m venv venv
source venv/bin/activate
python -m pip install -e ".[all,dev]"
zermes
```

## Hermes 社区和文档

Zermes 构建在 Hermes Agent 之上，因此上游 Hermes 的大量文档和社区经验仍适用于共享的运行时、CLI 概念、模型提供商、消息网关、工具、技能、记忆和定时任务：

- Hermes 文档：[hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)
- Hermes / Nous Research 社区：[Discord](https://discord.gg/NousResearch)
- Skills Hub：[agentskills.io](https://agentskills.io)
- 上游 Hermes 仓库：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)

部分 Zermes 行为，尤其是有治理的自我进化和源码运行时安装器，可能与上游 Hermes 文档不同。

## 版权和许可证

Zermes 以 MIT License 分发。详见 [LICENSE](LICENSE)。

Zermes 基于 Hermes Agent，并在 Hermes 代码库基础上进行了面向 Zermes 命名、安装流程、运行时布局和有治理自我进化工作流的修改。

原始 Hermes Agent 项目的版权由 Nous Research 保留：

```text
Copyright (c) 2025 Nous Research
```

Zermes 特定修改的版权由 Zermes contributors 保留：

```text
Copyright (c) 2026 Zermes contributors
```

除非文件另有说明，原始 Hermes 代码和 Zermes 修改均按 MIT License 提供。
