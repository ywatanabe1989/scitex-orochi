# Calling peer agents via A2A

Every fleet agent has an A2A endpoint at `https://a2a.scitex.ai/v1/agents/<id>`. To **call** another agent (rather than just be called), an agent needs three things: the URL, an A2A bearer token, and a JSON-RPC client.

## Surfaces

| Component | Where | Public? |
| --- | --- | --- |
| A2A discovery + JSON-RPC server | `scitex-cloud/apps/infra/a2a_app/` (NAS) | Public |
| AgentCard projection from v3 YAML | same | Public |
| Per-agent A2A token | `~/.bash.d/secrets/010_scitex/orochi-gitea-agents/<id>.a2a-token` | **Private** (dotfiles git) |
| A2A client convention | this skill | Public |

## Token model

- **Bearer = the caller's own Gitea PAT**, scoped `read:user`.
- Server validates by calling `Gitea GET /api/v1/user` with that bearer; identity in response = caller.
- Each agent has TWO tokens: `<id>.gitea-token` (broad, for fork/PR) and `<id>.a2a-token` (narrow, for A2A only). A2A leak ≠ git compromise.
- Humans use their own PAT the same way.

## Injection — pick the port

See `scitex-agent-container/06_env-injection-ports.md` for the three ports.

| Caller | Port | YAML/JSON snippet |
| --- | --- | --- |
| Bash/curl from agent shell | `spec.env` (port 1) | `SCITEX_OROCHI_A2A_TOKEN_PATH: ~/.bash.d/secrets/010_scitex/orochi-gitea-agents/${SCITEX_AGENT_NAME}.a2a-token` |
| MCP tool (recommended) | `src_mcp.json env` (port 2) | `"SCITEX_OROCHI_A2A_TOKEN": "${SCITEX_OROCHI_A2A_TOKEN}"` (parent shell sources from token file before launching sac) |
| Hook | n/a — hooks can't inject env into the agent |

The MCP route (port 2) is preferred: agents call `mcp__scitex-orochi__a2a_call(agent="lead", method="tasks/send", message="hi")` and never see the token in their transcript.

## Wire-level call

```bash
TOKEN=$(cat "$SCITEX_OROCHI_A2A_TOKEN_PATH")
curl -fsSL -X POST https://a2a.scitex.ai/v1/agents/lead \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"t1","method":"tasks/send",
       "params":{"message":{"role":"user","parts":[{"type":"text","text":"hi"}]}}}'
```

GET endpoints (`/v1/agents/`, `/.well-known/agent.json`) stay public and unauthenticated — they are the discovery surface.

## Don'ts

- Don't bake tokens into prompts or `src_CLAUDE.md` — they end up in transcripts forever.
- Don't reuse `<id>.gitea-token` for A2A — broader scope = larger blast radius on leak.
- Don't put fleet-specific token paths in this public skill — those go in `scitex-orochi-private/`.

## Cross-refs

- Master nav: `~/proj/scitex-orochi/GITIGNORED/A2A_PROTOCOL_SUPPORT.md`
- Cloud-side ops: `~/proj/scitex-cloud/GITIGNORED/A2A_PROTOCOL_SUPPORT-CLOUD.md`
- Identity: `~/proj/scitex-orochi/GITIGNORED/GITEA_FORK_MODEL.md`
- sac env ports: `scitex-agent-container/06_env-injection-ports.md`
