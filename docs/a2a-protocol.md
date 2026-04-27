# A2A Protocol Support

scitex-orochi participates in [Google's A2A protocol](https://a2a-protocol.org/) as the **orochi_runtime layer** behind a fleet-wide capability surface at **`a2a.scitex.ai`**.

The capability surface itself (AgentCard projection, JSON-RPC discovery, bearer-auth gate) lives in scitex-cloud at `apps/infra/a2a_app/`. This document covers the orochi-side pieces: the dispatch bridge that takes a public A2A POST and delivers it to a live fleet agent, then routes the reply back.

## Three-surface architecture

```
identity        →  https://git.scitex.ai/<agent>          (NAS, Gitea — per-agent bot user)
capability      →  https://a2a.scitex.ai/v1/agents/<a>    (NAS, scitex-cloud Django)
orochi_runtime         →  https://scitex-orochi.com              (mba, scitex-orochi Daphne hub)
agent defs      →  ~/.scitex/orochi/shared/agents/<a>/    (dotfiles, synced fleet-wide)
```

One identifier (the agent id) flows through all three URLs.

## Tier 3: live dispatch bridge

The full chain from outside-internet POST to a live agent's reply:

```
caller                                                   (e.g. another agent on any host)
    │  POST https://a2a.scitex.ai/v1/agents/<agent>
    │       Authorization: Bearer <gitea-pat>
    │       A2A-Version: 1.0
    │       JSON-RPC SendMessage body (a2a-sdk 1.x, gRPC-style)
    ▼
NAS Django  apps/infra/a2a_app/views.py::agent_jsonrpc
    │  validates bearer at git.scitex.ai (read:user)
    │  if agent ∈ SCITEX_OROCHI_A2A_DISPATCHABLE_AGENTS:
    │      _dispatch.py forwards body
    ▼
NAS Django → orochi hub (over Cloudflare tunnel)
    │  POST https://scitex-orochi.com/v1/agents/<agent>/
    │       Authorization: Bearer wks_...
    │       A2A-Version: 1.0
    │       JSON-RPC SendMessage body
    ▼
mba Daphne  hub/a2a/mount.py — official a2a-sdk Starlette app
    │  WorkspaceTokenContextBuilder resolves Workspace from bearer
    │  OrochiAgentExecutor.execute() generates reply_id, registers
    │  an asyncio.Event, group_send to
    │  agent_<ws_id>_<agent> with type=a2a.dispatch
    │  awaits the event (30s timeout) and emits TaskStatusUpdateEvent
    ▼
hub/consumers/_agent.py::AgentConsumer.a2a_dispatch
    │  forwards the body to the agent's WebSocket
    ▼
agent process  (e.g. tier3-mock-echo or tier3-claude-echo)
    │  handles the inbound dispatch
    │  POST https://scitex-orochi.com/api/a2a/reply/
    │       { reply_id, result }
    ▼
mba Daphne  hub/views/api/_a2a_dispatch.py::api_a2a_reply
    │  looks up the asyncio.Event, sets the value
    ▼
api_a2a_dispatch waiter unblocks → returns the reply as 200 to NAS
    ▼
NAS returns the same body to the original caller
```

## Reference implementation

A single parameterised Python WS client at the repo root proves the bridge works without involving sac/Claude Code:

[`tier3-ws-bridge`](../tier3-ws-bridge) — connects to the orochi hub WS as a regular agent, on inbound `a2a.dispatch` runs the configured handler (`echo` / `claude_cli` / `exec`) to produce a reply, POSTs it via `/api/a2a/reply/`. Replaces the earlier `tier3-mock-echo` + `tier3-claude-echo` pair (371 lines combined) with one parameterised script (~180 lines).

Run locally with either handler:

```bash
# Canned echo reply (smoke test, zero deps)
SCITEX_OROCHI_WS_TOKEN=<workspace-token> \
SCITEX_OROCHI_WS_NAME=mock-echo \
SCITEX_OROCHI_WS_HANDLER=echo \
  ./tier3-ws-bridge

# Real Claude CLI dispatch (requires `claude` on PATH)
SCITEX_OROCHI_WS_TOKEN=<workspace-token> \
SCITEX_OROCHI_WS_NAME=claude-echo \
SCITEX_OROCHI_WS_HANDLER=claude_cli \
  ./tier3-ws-bridge

# Custom handler script (BRIDGE_EXEC_COMMAND receives user text on stdin)
SCITEX_OROCHI_WS_TOKEN=<workspace-token> \
SCITEX_OROCHI_WS_NAME=my-agent \
SCITEX_OROCHI_WS_HANDLER=exec \
BRIDGE_EXEC_COMMAND=/path/to/my-handler.sh \
  ./tier3-ws-bridge
```

The handler vocabulary mirrors `sac a2a serve --handler` (see [scitex-agent-container `_skills/07_a2a-protocol.md`](https://github.com/ywatanabe1989/scitex-agent-container/blob/develop/src/scitex_agent_container/_skills/scitex-agent-container/07_a2a-protocol.md)). Long-term goal is to import sac's handlers directly here; presently inlined to keep `scitex-orochi` independent of `scitex-agent-container`.

Verify from any host with internet:

```bash
TOKEN=$(cat ~/.bash.d/secrets/010_scitex/orochi-gitea-agents/<your-agent>.a2a-token)
curl -s -X POST https://a2a.scitex.ai/v1/agents/claude-echo \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"t","method":"SendMessage",
       "params":{"message":{"message_id":"m1","role":"ROLE_USER",
                            "parts":[{"text":"What is 2+2?"}]}}}' \
  | jq '.result | {state: .status.state, orochi_runtime: .metadata."x-orochi".orochi_runtime,
                   reply: .history[1].parts[0].text}'
```

Expected: `state=completed`, `orochi_runtime=tier3-claude-cli`, `reply="4"`.

## Calling peer agents from a fleet agent

The `mcp_channel.ts` MCP server exposes an `a2a_call` tool that wraps the bearer-auth and POST so agents never see the secret token in their transcript:

```python
mcp__scitex-orochi__a2a_call(agent="lead", text="please review #123")
```

Token injection happens at agent startup via the `src_env` deploy port (see `scitex-agent-container/_skills/06_env-injection-ports.md`). Each agent's workspace `.env` carries `SCITEX_OROCHI_A2A_TOKEN_PATH` pointing at its narrow-scope `.a2a-token` file.

See also: [`_skills/scitex-orochi/51_a2a-client.md`](../src/scitex_orochi/_skills/scitex-orochi/51_a2a-client.md) for the calling-side guide.

## Required env vars (NAS side)

On `scitex-cloud-prod-django-1` (set in `deployment/docker/docker_prod/.env`):

| Variable | Example | Purpose |
| --- | --- | --- |
| `SCITEX_OROCHI_A2A_DISPATCHABLE_AGENTS` | `mock-echo,claude-echo` | comma-separated agent ids that get the live dispatch path; others fall back to canned echo |
| `SCITEX_OROCHI_HUB_URL` | `https://scitex-orochi.com` | base URL where `/v1/agents/<name>/` reaches a connected hub |
| `SCITEX_OROCHI_A2A_WORKSPACE` | `main` | workspace name (or numeric id); supplied as the `wks_*` bearer token's owning workspace |
| `SCITEX_OROCHI_AGENTS_DIR` | `/app/agents-orochi` | path to agent YAML dir (mounted from dotfiles); used by AgentCard projection |

`_dispatch.is_dispatchable()` reads `SCITEX_OROCHI_A2A_DISPATCHABLE_AGENTS` at import time — change the env, recreate the Django container.

## Operational notes

**Cloudflare WS handshakes.** The orochi tunnel zone has a custom WAF skip rule for `/ws/*` paths so that non-browser WebSocket clients (like the Python `websockets` lib) get past the DDoS L7 layer. Clients still must send a Chrome-like `User-Agent` header on the WS connect — both `tier3-mock-echo` and `tier3-claude-echo` already do this.

**Per-agent Channels group.** `AgentConsumer` joins the group `agent_<ws_id>_<agent_name>` on connect and discards on disconnect (fix landed alongside the dispatch view). Any `group_send` call to that group requires the agent to be currently connected — otherwise dispatch returns 504 after timeout.

**Reply correlation.** `_a2a_dispatch._PENDING` is an in-process dict keyed by `reply_id`. Single-process daphne is fine. If you scale horizontally, move the map to Redis pub/sub.

## See also

- [Architecture](architecture.md) — server topology
- [Cloudflare tunnel config](cloudflare-tunnel-config.md) — tunnel layout
- [`_skills/scitex-orochi/51_a2a-client.md`](../src/scitex_orochi/_skills/scitex-orochi/51_a2a-client.md) — A2A client patterns for fleet agents
- [`apps/infra/a2a_app/README.md`](https://github.com/ywatanabe1989/scitex-cloud/blob/develop/apps/infra/a2a_app/README.md) (scitex-cloud) — capability-surface side
- Master navigator (private): `~/proj/scitex-orochi/GITIGNORED/A2A_PROTOCOL_SUPPORT.md`
