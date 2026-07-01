# Gateway Interfaces Reference

> Gateway entry: `hermes gateway`

## Messaging Platforms

| Platform | Config Key | Adapter | Features |
|---|---|---|---|
| Telegram | `telegram` | `telegram.py` | Full messaging, topics, inline keyboards, media |
| Discord | `discord` | `discord.py` | Full messaging, threads, slash commands, embeds |
| WhatsApp | `whatsapp` | `whatsapp.py` | Messaging, media |
| Slack | `slack` | `slack.py` | Messaging, blocks, channels |
| Signal | `signal` | `signal.py` | Messaging |
| Mattermost | `mattermost` | `mattermost.py` | Messaging |
| Matrix | `matrix` | `matrix.py` | Messaging |
| DingTalk | `dingtalk` | `dingtalk.py` | Messaging, AI cards |
| Feishu | `feishu` | `feishu.py` | Messaging, comments, rich content |
| WeCom | `wecom` | `wecom.py` | Messaging, callback, crypto |
| Weixin | `weixin` | `weixin.py` | Messaging |
| Home Assistant | `homeassistant` | `homeassistant.py` | Home automation integration |
| BlueBubbles | `bluebubbles` | `bluebubbles.py` | iMessage bridge |
| QQ Bot | `qqbot` | `qqbot/` (package) | Messaging, keyboards, uploads |
| Yuanbao | `yuanbao` | `yuanbao.py` | Messaging, media, stickers |
| Email | `email` | `email.py` | Email send/receive |
| SMS | `sms` | `sms.py` | SMS send/receive |
| Webhook | `webhook` | `webhook.py` | Incoming webhooks |
| MSGraph Webhook | `msgraph_webhook` | `msgraph_webhook.py` | Microsoft Graph webhook receiver (Teams, Outlook), lifecycle notifications |

## API Server

The Gateway includes an OpenAI-compatible API server (`api_server.py`) that can serve any OpenAI-compatible frontend (Chatbox, NextChat, LobeChat, LibreChat, etc.).

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | Chat completions (stream + non-stream) |
| `POST` | `/v1/chat/completions/:cid` | Continue a previous completion (session-aware) |
| `GET` | `/v1/models` | List available models |
| `GET` | `/health` | Health check |
| `GET` | `/v1/agent/status` | Session agent status |

### API Server features

- Streaming with SSE (`stream=true`)
- Tool/function calling
- Multi-turn conversations via session management
- Authentication via configurable API keys

### Example request

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

## Gateway Commands

These slash commands are available on messaging platforms through the Gateway:

| Command | Aliases | Args | Description |
|---|---|---|---|
| `/new` | `reset` | `[name]` | Start a new session |
| `/topic` | — | `[off\|help\|session-id]` | Enable or inspect Telegram DM topic sessions |
| `/retry` | — | — | Retry the last message |
| `/undo` | — | — | Remove the last user/assistant exchange |
| `/title` | — | `[name]` | Set a title for the current session |
| `/branch` | `fork` | `[name]` | Branch the current session |
| `/compress` | — | `[focus topic]` | Compress conversation context |
| `/rollback` | — | `[number]` | List or restore checkpoints |
| `/stop` | — | — | Stop the running agent |
| `/background` | `bg`, `btw` | `<prompt>` | Run a prompt in the background |
| `/agents` | `tasks` | — | Show active agents and running tasks |
| `/queue` | `q` | `<prompt>` | Queue a prompt for the next turn |
| `/steer` | — | `<prompt>` | Inject a message after the next tool call |
| `/goal` | — | `[text\|pause\|resume\|clear\|status]` | Set a standing goal |
| `/approve` | — | `[session\|always]` | Approve a pending dangerous command |
| `/deny` | — | — | Deny a pending dangerous command |
| `/sethome` | `set-home` | — | Set this chat as the home channel |
| `/resume` | — | `[name]` | Resume a previously-named session |
| `/restart` | — | — | Gracefully restart the gateway |
| `/model` | `provider` | `[model]` | Switch model for this session |
| `/personality` | — | `[name]` | Set a predefined personality |
| `/reasoning` | — | `[level\|show\|hide]` | Manage reasoning effort |
| `/fast` | — | `[normal\|fast\|status]` | Toggle fast mode |
| `/verbose` | — | — | Cycle tool progress display |
| `/footer` | — | `[on\|off\|status]` | Toggle runtime-metadata footer |
| `/yolo` | — | — | Toggle YOLO mode |
| `/help` | — | — | Show available commands |
| `/commands` | — | `[page]` | Browse all commands and skills (paginated) |
| `/profile` | — | — | Show active profile |
| `/usage` | — | — | Show token usage and rate limits |
| `/insights` | — | `[days]` | Show usage insights |
| `/update` | — | — | Update Hermes to the latest version |
| `/debug` | — | — | Upload debug report |
| `/kanban` | — | `[subcommand]` | Multi-profile collaboration board |
| `/curator` | — | `[subcommand]` | Background skill maintenance |
| `/voice` | — | `[on\|off\|tts\|status]` | Toggle voice mode |
| `/reload-mcp` | `reload_mcp` | — | Reload MCP servers from config |
| `/reload-skills` | `reload_skills` | — | Re-scan skills directory |
| `/status` | — | — | Show session info |

## Config Reference

```yaml
# gateway.yaml
gateway:
  adapters:
    telegram:
      enabled: true
      token: "${TELEGRAM_BOT_TOKEN}"
    discord:
      enabled: true
      token: "${DISCORD_BOT_TOKEN}"
  api_server:
    enabled: true
    host: "0.0.0.0"
    port: 8080
    api_key: "${API_SERVER_KEY}"
  session:
    expiry_hours: 24
    max_concurrent_agents: 128
  streaming:
    edit_interval: 1.0
    buffer_threshold: 40
    cursor: " ▉"

provider_routing:
  telegram:
    model: "claude-sonnet-4-20250514"
  discord:
    model: "gpt-4o"
  api_server:
    model: "claude-sonnet-4-20250514"
```

## Hook System

The Gateway supports declarative hooks (`gateway/plugins/hook_registry.py`):

| Hook | Trigger |
|---|---|
| `command:<name>` | Before command execution |
| `message:receive` | User message received |
| `message:send` | Before message is sent |
| `agent:start` | Agent begins execution |
| `agent:complete` | Agent finishes execution |
| `session:finalize` | Session ends |

Each hook returns `{"decision": "allow"|"deny"|"handled"|"rewrite", ...}` to control the message flow.