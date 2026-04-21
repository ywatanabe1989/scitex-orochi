---
name: orochi-cli-conventions
description: scitex-orochi CLI specialization — concrete noun catalog, server/client split, (Available Now) suffix, --json introspection schema with requires_service tagging, local/hub/both classification, NDJSON event-stream contract, MCP parity. Defers to the canonical SciTeX CLI convention for everything else.
---

# scitex-orochi CLI Convention (specialization)

> **This skill is a specialization of the canonical SciTeX CLI convention.**
>
> Canonical rules (noun-verb structure, universal flags, exit codes,
> help format, deprecation redirect, env var namespace, config file
> precedence, MCP parity, stdout/stderr, audit checklist) live at:
>
> `scitex-python/src/scitex/_skills/general/interface-cli.md`
>
> This file only covers scitex-orochi-specific rules and naming.

## 1. Noun catalog

Top-level nouns currently exposed by `scitex-orochi`:

| Noun | Purpose |
|---|---|
| `agent` | Launch / control / list fleet agents |
| `channel` | Channel operations (list, history, join, members) |
| `message` | Send / listen / react on messages |
| `workspace` | Create / delete / list workspaces |
| `machine` | Heartbeat, probe, resource reporting |
| `todo` | Fleet todo management |
| `dispatch` | Server-side dispatch control |
| `cron` | Schedule daemon control |
| `push` | Push-notification setup |
| `invite` | Invite create / list |
| `auth` | Login |
| `system` | `system doctor` health check |
| `hook` | Hook reporting |
| `config` | Config init |
| `server` | Server lifecycle (start / status / deploy) |

Verbs sit under each noun per the canonical noun-verb rule.

## 2. Server / client split

scitex-orochi has both a **hub/server side** and a **client/local
side**. Subcommands may prefix the noun with `server` or `client`:

```
scitex-orochi server <noun> <verb>
scitex-orochi client <noun> <verb>
```

Humans rarely type these — the length is acceptable. The split makes
every subcommand unambiguous about "local execution vs hub-routed",
which matters for scitex-orochi because most nouns have both sides.

Packages without a hub/client split do not use this layer.

## 3. `(Available Now)` quiet suffix

**Policy:** when a subcommand depends on a live external service
(hub, database, MCP server, SSH tunnel, remote API) and that service
is currently reachable, append `(Available Now)` to the subcommand's
one-line description. When it is not reachable: **drop the suffix
silently** — no red text, no banner, no popup, no "unavailable"
warning. "Minimum surprise".

Example:

```
scitex-orochi server --help:
  workspace  Manage workspaces             (Available Now)
  channel    Manage channels               (Available Now)
  todo       Todo management               (Available Now)

scitex-orochi client --help:
  agent      Launch/control agents         (Available Now)
  machine    Heartbeat, probe, resources   (Available Now)
  cron       Schedule daemon               (Available Now)
```

**Implementation rules:**
- Probe must be `≤100ms` and non-blocking (click eager callback or
  argparse pre-hook)
- Cache the probe result for the duration of the process
- Probe failures silently remove the tag, never crash help rendering
- No color codes, no emojis, no unicode symbols — plain text only
- When `--json` is set, emit an `available_now: true|false` field
  instead of the suffix

## 4. `--json` introspection schema

`--json` on a group command must emit:

```json
{
  "command": "scitex-orochi",
  "version": "X.Y.Z",
  "subcommands": [
    {
      "name": "agent",
      "description": "Launch/control agents",
      "available_now": true,
      "verbs": [
        {"name": "list", "description": "...", "requires_service": false},
        {"name": "launch", "description": "...", "requires_service": true}
      ]
    }
  ]
}
```

Schema lives at `src/scitex_orochi/_cli/schemas/help.json`.

## 5. Local / hub / both classification

Every scitex-orochi subcommand must be tagged internally as one of:

| Class | Meaning |
|---|---|
| `local` | Runs entirely on the caller's machine |
| `hub` | Requires the Orochi hub to be reachable |
| `both` | Works local-only, with hub as optional enrichment |

The `--json` help emits this class as
`requires_service: false|true|optional`. The `(Available Now)` suffix
reflects hub reachability only for the `hub` and `both` cases; `local`
commands always show the suffix (because the "local service" is the
caller's own binary).

## 6. NDJSON event-stream schema contract

scitex-orochi emits NDJSON (one JSON object per line) on several
streams (channel history, dispatch events, heartbeat log). For every
NDJSON-emitting command:

1. Publish the schema at `src/scitex_orochi/_cli/schemas/ndjson.json`
2. Maintain byte-level compatibility across minor releases (adding
   new fields is fine; removing or renaming fields is a breaking
   change requiring a major version bump)
3. Include a `"schema_version": "N"` field on every event
4. Provide `tests/test_cli_ndjson_schema.py` validating sample outputs
   against the schema

## 7. MCP tool parity (concrete mappings)

scitex-orochi CLI subcommands and their MCP tool counterparts:

| CLI subcommand | MCP tool |
|---|---|
| `scitex-orochi message send` | `mcp__scitex-orochi__reply` |
| `scitex-orochi message react add` | `mcp__scitex-orochi__react` |
| `scitex-orochi channel history` | `mcp__scitex-orochi__history` |
| `scitex-orochi channel members` | `mcp__scitex-orochi__channel_members` |
| `scitex-orochi channel list` | `mcp__scitex-orochi__my_subscriptions` |
| `scitex-orochi system doctor` | `mcp__scitex-orochi__health` / `mcp__scitex-orochi__status` |

Same argument names, same JSON output shape. The canonical MCP parity
rule (argument/shape/name matching) lives in the canonical CLI
convention; this table is the concrete mapping.

## 8. Env var naming — concrete violations

The canonical rule ("`SCITEX_<PACKAGE>_*` namespace, bare prefixes
forbidden") applies. Concrete forbidden → required examples in the
orochi surface:

| Forbidden | Required |
|---|---|
| `OROCHI_AGENT` | `SCITEX_OROCHI_AGENT` |
| `OROCHI_TOKEN` | `SCITEX_OROCHI_TOKEN` |
| `OROCHI_HOST` | `SCITEX_OROCHI_HOST` |
| `OROCHI_MULTIPLEXER` | `SCITEX_OROCHI_MULTIPLEXER` |

Audit command: `grep -rE '^OROCHI_|[^A-Z_]OROCHI_' src/` finds
remaining bare-prefix callers. Rename and update references in one
commit.

## 9. Cross-references

- Canonical: `scitex-python/src/scitex/_skills/general/interface-cli.md`
- Concrete audit checklist: see canonical §9
- Universal flags / exit codes / help format / deprecation redirect:
  see canonical §§2–5

<!-- EOF -->
