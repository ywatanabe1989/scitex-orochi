# A2A Protocol Support

scitex-orochi participates in [Google's A2A protocol](https://a2a-protocol.org/) as the **runtime layer** behind a fleet-wide capability surface at **`a2a.scitex.ai`**.

The capability surface itself (AgentCard projection, JSON-RPC discovery, bearer-auth gate) lives in scitex-cloud at `apps/infra/a2a_app/`. This document covers the orochi-side pieces: the dispatch bridge that takes a public A2A POST and delivers it to a live fleet agent, then routes the reply back.

## Three-surface architecture

```
identity        →  https://git.scitex.ai/<agent>          (NAS, Gitea — per-agent bot user)
capability      →  https://a2a.scitex.ai/v1/agents/<a>    (NAS, scitex-cloud Django)
runtime         →  https://scitex-orochi.com              (mba, scitex-orochi Daphne hub)
agent defs      →  ~/.scitex/orochi/shared/agents/<a>/    (dotfiles, synced fleet-wide)
```

One identifier (the agent id) flows through all three URLs.

## Tier 3: live dispatch bridge

The full chain from outside-internet POST to a live agent's reply:

```
caller                                                   (e.g. another agent on any host)
    │  POST https://a2a.scitex.ai/v1/agents/<agent>
    │       Authorization: Bearer <gitea-pat>
    │       JSON-RPC tasks/send body
    ▼
NAS Django  apps/infra/a2a_app/views.py::agent_jsonrpc
    │  validates bearer at git.scitex.ai (read:user)
    │  if agent ∈ SCITEX_OROCHI_A2A_DISPATCHABLE_AGENTS:
    │      _dispatch.py forwards body
    ▼
NAS Django → orochi hub (over Cloudflare tunnel)
    │  POST https://scitex-orochi.com/api/a2a/dispatch/<workspace>/<agent>/
    ▼
mba Daphne  hub/views/api/_a2a_dispatch.py::api_a2a_dispatch
    │  generates reply_id, registers an asyncio.Event, group_send to
    │  agent_<ws_id>_<agent> with type=a2a.dispatch
    │  blocks waiting for the event (30s timeout)
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

## Reference implementations

Two minimal Python WS clients live at the repo root and prove the bridge works without involving sac/Claude Code:

| Script | What it does |
| --- | --- |
| [`tier3-mock-echo`](../tier3-mock-echo) | canned A2A echo reply — used as the smoke-test agent |
| [`tier3-claude-echo`](../tier3-claude-echo) | runs `claude --print` on the user message and forwards stdout — proves real-LLM dispatch |

Both connect to the orochi hub WS as a regular agent (with a workspace token), join the per-agent Channels group, and post replies via `/api/a2a/reply/`.

Run locally:

```bash
SCITEX_OROCHI_WS_TOKEN=<workspace-token> ./tier3-mock-echo
SCITEX_OROCHI_WS_TOKEN=<workspace-token> ./tier3-claude-echo
```

Verify from any host with internet:

```bash
TOKEN=$(cat ~/.bash.d/secrets/010_scitex/orochi-gitea-agents/<your-agent>.a2a-token)
curl -s -X POST https://a2a.scitex.ai/v1/agents/claude-echo \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"t","method":"tasks/send",
       "params":{"message":{"role":"user","parts":[{"type":"text","text":"What is 2+2?"}]}}}' \
  | jq '.result | {state: .status.state, runtime: .metadata."x-orochi".runtime,
                   reply: .history[1].parts[0].text}'
```

Expected: `state=completed`, `runtime=tier3-claude-cli`, `reply="4"`.

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
| `SCITEX_OROCHI_HUB_URL` | `https://scitex-orochi.com` | base URL where `/api/a2a/dispatch/...` reaches a connected hub |
| `SCITEX_OROCHI_A2A_WORKSPACE` | `main` | workspace name (or numeric id) used in the dispatch URL path |
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
