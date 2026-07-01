# CLI Commands Reference

> Hermes CLI entry: `hermes`

## Session

| Command | Aliases | Args | Description |
|---|---|---|---|
| `/new` | `reset` | `[name]` | Start a new session (fresh session ID + history) |
| `/clear` | — | — | Clear screen and start a new session |
| `/delete-context` | — | — | Delete chat context and DB messages without starting a new session |
| `/redraw` | — | — | Force a full UI repaint (recovers from terminal drift) |
| `/history` | — | — | Show conversation history |
| `/save` | — | — | Save the current conversation |
| `/retry` | — | — | Retry the last message (resend to agent) |
| `/undo` | — | — | Remove the last user/assistant exchange |
| `/title` | — | `[name]` | Set a title for the current session |
| `/branch` | `fork` | `[name]` | Branch the current session (explore a different path) |
| `/compress` | — | `[focus topic]` | Manually compress conversation context |
| `/rollback` | — | `[number]` | List or restore filesystem checkpoints |
| `/snapshot` | `snap` | `[create\|restore <id>\|prune]` | Create or restore state snapshots of Hermes config/state |
| `/stop` | — | — | Kill all running background processes |
| `/background` | `bg`, `btw` | `<prompt>` | Run a prompt in the background |
| `/agents` | `tasks` | — | Show active agents and running tasks |
| `/queue` | `q` | `<prompt>` | Queue a prompt for the next turn (doesn't interrupt) |
| `/steer` | — | `<prompt>` | Inject a message after the next tool call without interrupting |
| `/goal` | — | `[text \| pause \| resume \| clear \| status]` | Set a standing goal the agent works on across turns |
| `/status` | — | — | Show session info |
| `/resume` | — | `[name]` | Resume a previously-named session |
| `/sessions` | — | — | Browse and resume previous sessions |

## Configuration

| Command | Aliases | Args | Description |
|---|---|---|---|
| `/config` | — | — | Show current configuration |
| `/model` | `provider` | `[model] [--provider name] [--global]` | Switch model for this session |
| `/gquota` | — | — | Show Google Gemini Code Assist quota usage |
| `/personality` | — | `[name]` | Set a predefined personality |
| `/statusbar` | `sb` | — | Toggle the context/model status bar |
| `/verbose` | — | — | Cycle tool progress display: off → new → all → verbose |
| `/footer` | — | `[on\|off\|status]` | Toggle gateway runtime-metadata footer on final replies |
| `/yolo` | — | — | Toggle YOLO mode (skip all dangerous command approvals) |
| `/reasoning` | — | `[level\|show\|hide]` | Manage reasoning effort and display |
| `/fast` | — | `[normal\|fast\|status]` | Toggle fast mode — Priority Processing / Fast Mode |
| `/skin` | — | `[name]` | Show or change the display skin/theme |
| `/indicator` | — | `[kaomoji\|emoji\|unicode\|ascii]` | Pick the TUI busy-indicator style |
| `/voice` | — | `[on\|off\|tts\|status]` | Toggle voice mode |
| `/busy` | — | `[queue\|steer\|interrupt\|status]` | Control what Enter does while the agent is working |

## Tools & Skills

| Command | Aliases | Args | Description |
|---|---|---|---|
| `/tools` | — | `[list\|disable\|enable] [name...]` | Manage tools |
| `/toolsets` | — | — | List available toolsets |
| `/skills` | — | — | Search, install, inspect, or manage skills |
| `/cron` | — | `[subcommand]` | Manage scheduled tasks |
| `/curator` | — | `[subcommand]` | Background skill maintenance (status, run, pin, archive) |
| `/kanban` | — | `[subcommand]` | Multi-profile collaboration board |
| `/reload` | — | — | Reload `.env` variables into the running session |
| `/reload-mcp` | `reload_mcp` | — | Reload MCP servers from config |
| `/reload-skills` | `reload_skills` | — | Re-scan skills directory for newly installed or removed skills |
| `/browser` | — | `[connect\|disconnect\|status]` | Connect browser tools to live Chrome via CDP |
| `/plugins` | — | — | List installed plugins and their status |

## Info

| Command | Aliases | Args | Description |
|---|---|---|---|
| `/help` | — | — | Show available commands |
| `/profile` | — | — | Show active profile name and home directory |
| `/usage` | — | — | Show token usage and rate limits for the current session |
| `/insights` | — | `[days]` | Show usage insights and analytics |
| `/platforms` | `gateway` | — | Show gateway/messaging platform status |
| `/copy` | — | `[number]` | Copy the last assistant response to clipboard |
| `/paste` | — | — | Attach clipboard image from clipboard |
| `/image` | — | `<path>` | Attach a local image file for the next prompt |
| `/debug` | — | — | Upload debug report (system info + logs) and get shareable links |

## Exit

| Command | Aliases | Args | Description |
|---|---|---|---|
| `/quit` | `exit` | — | Exit the CLI |

## Launch Modes

| Command | Description |
|---|---|
| `hermes` | Interactive CLI (default) |
| `hermes <prompt>` | One-shot prompt, then exit |
| `hermes <prompt> -p` | One-shot prompt, print result to stdout |
| `hermes -m <model>` | Start with a specific model |
| `hermes --profile <name>` | Start with a specific profile |
| `hermes gateway` | Start the messaging gateway |
| `hermes web` | Start the web dashboard (legacy) |
| `hermes --tui` | Start the TUI interface (legacy) |