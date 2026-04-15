---
name: orochi-resource-hub
description: Fleet-wide aggregation of per-host scitex-resource caches so any agent can query live capacity across hosts without ssh-ing everywhere.
---

# Resource Hub

Aggregates `~/.scitex/cache/` from every fleet host into a single view on the Orochi hub (MBA). Downstream consumers (e.g. planning agents) then see fleet state without hitting each host.

## Architecture

```
each host: heartbeat/collect.sh (tmux or cron) -> ~/.scitex/cache/*.txt
                              |
                              v  (pull via rsync from hub)
hub (MBA):  ~/.scitex/fleet-cache/<host>/*.txt
                              |
                              v
       scitex-resource CLI / scripts read from here for cross-fleet views
```

## Transport

Start with rsync pull from the hub. Simpler and failure-soft: if a host is unreachable, its last-known cache stays on the hub until the next successful pull.

```bash
# ~/.scitex/bin/pull-fleet-caches.sh
for h in spartan mba nas ywata-note-win; do
  dest="${HOME}/.scitex/fleet-cache/${h}"
  mkdir -p "${dest}"
  rsync -az --timeout=5 \
    "${h}:.scitex/cache/" "${dest}/" 2>/dev/null || true
done
```

Schedule under system cron on the hub (every 60s):
```cron
* * * * * ~/.scitex/bin/pull-fleet-caches.sh >> ~/.scitex/fleet-cache.log 2>&1
```

## Channel Convention

- `#escalation` — heartbeat gone stale >5 min on any host → one alert per host, deduped by a watcher script (not by Claude Code).
- `#progress` — daily rollup of fleet utilization (who's hot, who's idle), posted by a lightweight cron-driven summary script.
- **Do not** push raw cache contents to any Orochi channel — it's noisy and not useful to humans. Agents read the aggregated files directly.

## Staleness & Death Detection

Hub runs a plain cron watcher (no Claude Code):

```bash
now=$(date +%s)
for f in ~/.scitex/fleet-cache/*/last_update.txt; do
  host=$(basename "$(dirname "$f")")
  ts=$(date -d "$(cat "$f")" +%s 2>/dev/null || echo 0)
  age=$(( now - ts ))
  if [ "$age" -gt 300 ]; then
    echo "stale:${host}:${age}s"
  fi
done
```

Pipe to a deduping alerter that posts to `#escalation` (one alert per host per outage, not per tick).

## Consumer Access

Agents running on the hub can read aggregated caches directly:

```python
from pathlib import Path

fleet_dir = Path.home() / ".scitex" / "fleet-cache"
for host_dir in fleet_dir.iterdir():
    nodes = (host_dir / "slurm_nodes.txt").read_text()
    last_update = (host_dir / "last_update.txt").read_text().strip()
    ...
```

Agents on **other** hosts should ssh-cat their own `~/.scitex/cache/` locally rather than reaching into the hub.

## Non-Goals

- Not a scheduler — this hub only reports state.
- Not a metrics system — no Prometheus/Grafana. Optional downstream if someone wants it.
- Not authenticated — fleet-internal trust, ssh keys only.

## Related

- `scitex-agent-container/resource-heartbeat.md` — per-host sampler
- `scitex-agent-container/resource-management.md` — the reader API
- `fleet-communication-discipline.md` — channel etiquette
