<p align="center">
  <img src="assets/banner.png" alt="Zermes" width="100%">
</p>

# Zermes

<p align="center">
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
  <a href="https://hermes-agent.nousresearch.com/docs/"><img src="https://img.shields.io/badge/Hermes%20Docs-hermes--agent.nousresearch.com-FFD700?style=for-the-badge" alt="Hermes documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Hermes%20Community-Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Hermes community"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
</p>

Zermes is a Hermes Agent derivative focused on governed, code-level self-evolution. It keeps the practical Hermes runtime foundation: a terminal AI agent, configurable model providers, toolsets, skills, memory, scheduled work, and messaging gateways. On top of that base, Zermes emphasizes a safer path for improving the agent's own repository.

The preferred user-facing command is `zermes`. Hermes-compatible names and internal structure remain where they help migration, but new Zermes installs should use the Zermes source runtime installer and a Zermes-oriented runtime layout.

## Features

1. **Code-level self-evolution**

   Capability: Zermes can turn user feature requests, repository-improvement ideas, or scheduled self-evolution thinking candidates into approval-first implementation plans, then modify its own code on a dedicated task branch after explicit approval. Each code change is tied to explicit file lists, change records, verification plans, and verification results.

   Advantage: This gives the agent a practical path to improve its own repository while keeping the risky parts visible, reviewable, verifiable, and reversible instead of allowing untracked automatic rewrites.

   Best for: code-oriented AI agent projects that need continuous improvement while preserving approval, audit, and verification controls.

2. **Managed worker agents**

   Capability: Zermes provides the backend contract and service layer for employee-style agents. A `WorkerAgent` is a long-lived professional identity with its own profile, lifecycle state, role boundary, permissions, task records, runtime adapter, model and budget policy, private memory boundary, skill usage policy, and organization placement. Private worker chats, department chats, project chats, `@` mentions, broadcasts, and organization trees all route through governed paths.

   Advantage: This turns multi-agent collaboration from temporary, invisible subagent calls into user-present, permissioned, context-minimized, low-sensitivity, proposal-first teamwork. Internal WorkerAgents and external coding, media-generation, or research agents share runtime contracts and connect through adapters, making audits, handoffs, budget control, and governance extensions easier to manage.

   Best for: agent platforms that need long-lived role-based collaboration, department-level task ownership, external agent integration, organizational memory, and controlled team evolution. This capability currently covers the backend contract and service layer with focused tests under `tests/worker_agents`; a full end-user management UI is not yet shipped.

## Installation And Usage

### Recommended: Source Runtime Installer

Install from the default `main` branch:

```bash
git clone https://github.com/arcpis/zerme.git
cd zermes
python3 install.py install --install-deps --global-command
```

On Windows PowerShell, use `python` if that is your Python launcher:

```powershell
git clone https://github.com/arcpis/zerme.git
cd zermes
python install.py install --install-deps --global-command
```

The installer creates a managed runtime instead of running directly from a mutable development checkout. It can:

- copy the selected source into `<prefix>/runtime/releases/<release-id>/`;
- create the runtime virtual environment;
- install Python dependencies when `--install-deps` is provided;
- create launchers under `<prefix>/bin`;
- optionally expose the global `zermes` command for the current user;
- keep user data separate in the configured data directory.

Useful install options:

```bash
python3 install.py install --dry-run
python3 install.py install --prefix ~/.local/share/zermes --data-dir ~/.zermes --install-deps --global-command
python3 install.py install --no-install-deps
python3 install.py install --no-global-command
```

After installation:

```bash
zermes
zermes setup
zermes model
zermes tools
zermes gateway
zermes doctor
```

### Updating

Updates are built from an explicit source checkout. Pull the latest source first, then build and activate an update candidate:

```bash
cd zermes
git pull
python3 install.py update --current-source --install-deps --activate --restart
```

You can also update an installed runtime from another checkout:

```bash
python3 install.py update --prefix <prefix> --source <source-dir> --install-deps --activate
```

Useful update options:

```bash
python3 install.py update --current-source --no-activate
python3 install.py update --current-source --skip-verify
python3 install.py rollback --prefix <prefix>
```

`--no-activate` builds and verifies the candidate without switching `active.json`. `rollback` points the runtime back to the previous release without deleting releases.

### Uninstalling

Remove the installed software runtime while preserving user data:

```bash
python3 install.py uninstall --prefix <prefix>
```

Also remove the recorded data directory and the global command created by the installer:

```bash
python3 install.py uninstall --prefix <prefix> --remove-data --remove-global-command
```

Use `--dry-run` first if you want to inspect the uninstall intent:

```bash
python3 install.py uninstall --prefix <prefix> --dry-run
```

### Developer Checkout

For development, you can still work directly in a source checkout:

```bash
git clone https://github.com/arcpis/zerme.git
cd zermes
python3 -m venv venv
source venv/bin/activate
python -m pip install -e ".[all,dev]"
zermes
```

## Hermes Community And Documentation

Zermes is built on Hermes Agent, so much of the upstream Hermes documentation and community knowledge remains useful for the shared runtime, CLI concepts, providers, gateways, tools, skills, memory, and scheduling:

- Hermes documentation: [hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)
- Hermes / Nous Research community: [Discord](https://discord.gg/NousResearch)
- Skills Hub: [agentskills.io](https://agentskills.io)
- Upstream Hermes repository: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)

Some Zermes behavior, especially governed self-evolution and the source runtime installer, may differ from upstream Hermes documentation.

## Copyright And License

Zermes is distributed under the MIT License. See [LICENSE](LICENSE).

Zermes is based on Hermes Agent and contains modifications to the Hermes codebase for Zermes naming, installation flow, runtime layout, and governed self-evolution workflows.

Copyright for the original Hermes Agent project is retained by Nous Research:

```text
Copyright (c) 2025 Nous Research
```

Copyright for Zermes-specific modifications is retained by the Zermes contributors:

```text
Copyright (c) 2026 Zermes contributors
```

Both the original Hermes code and Zermes modifications are provided under the MIT License unless a file states otherwise.
