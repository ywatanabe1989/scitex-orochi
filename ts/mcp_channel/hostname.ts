/**
 * Canonical host-identity resolution for Orochi heartbeats.
 *
 * Mirrors the Python ``agent_meta_pkg._machine.resolve_machine_label`` and
 * ``scripts/client/resolve-hostname`` logic so TS clients produce the same
 * ``mba`` / ``nas`` / ``spartan`` / ``ywata-note-win`` label as the
 * Python-side heartbeat.
 *
 * Resolution order (first non-empty wins):
 *   1. Live ``os.hostname()`` (short form), mapped through
 *      ``spec.hostname_aliases`` from ``~/.scitex/orochi/shared/config.yaml``
 *      when an entry matches — e.g. ``Yusukes-MacBook-Air`` → ``mba``.
 *   2. Raw short ``os.hostname()`` — if no alias entry matches, use the
 *      live hostname verbatim. This is the proof-of-life identity:
 *      whatever the kernel says this process is running on.
 *   3. Env fallback (``SCITEX_OROCHI_HOSTNAME`` / ``SCITEX_OROCHI_MACHINE``
 *      / ``SCITEX_AGENT_CONTAINER_HOSTNAME``) — only honoured when
 *      ``hostname()`` returned an empty string. An env override that
 *      disagrees with a populated live hostname is ignored on purpose;
 *      that is how a stale ``mba`` env leaked into a spartan process
 *      before PR#309 (lead msg#15578).
 *
 * PR#309 flipped priority so ``hostname()`` beats env vars. That fix
 * reintroduced a different regression (ywatanabe msg#16102): raw host
 * names like ``Yusukes-MacBook-Air`` were shown on the Agents dashboard
 * instead of the canonical fleet short name ``mba``, because the TS
 * heartbeat skipped the ``hostname_aliases`` map that the Python
 * resolver had always applied. This module restores alias application
 * so the resolution order matches the shared config contract.
 */
import { hostname as osHostname, homedir } from "os";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const DEFAULT_CONFIG_PATH = join(
  homedir(),
  ".scitex",
  "orochi",
  "shared",
  "config.yaml",
);

/**
 * Parse ``spec.hostname_aliases`` out of the shared config YAML without
 * pulling in a full YAML dependency. The aliases block is a flat
 * ``key: value`` mapping (raw-hostname → canonical-short-name) and the
 * shared/config.yaml is tiny, so a tolerant line scanner is sufficient
 * — we never round-trip, never edit, only read known-shape entries.
 *
 * Returns an empty dict on any parse problem; host-identity resolution
 * must always succeed via the raw hostname fallback even if the config
 * file is missing or malformed.
 */
export function loadHostnameAliases(
  configPath: string = DEFAULT_CONFIG_PATH,
): Record<string, string> {
  try {
    if (!existsSync(configPath)) return {};
    const text = readFileSync(configPath, "utf-8");
    const aliases: Record<string, string> = {};
    let inSpec = false;
    let inAliases = false;
    let aliasesIndent = -1;
    for (const raw of text.split(/\r?\n/)) {
      // Strip inline comments after a ``#`` preceded by whitespace
      // (safe for this file — no ``#`` inside legitimate values).
      const line = raw.replace(/\s+#.*$/, "").replace(/\s+$/, "");
      if (!line.trim()) continue;
      const indent = line.length - line.trimStart().length;
      if (indent === 0) {
        inSpec = line.startsWith("spec:");
        inAliases = false;
        aliasesIndent = -1;
        continue;
      }
      if (!inSpec) continue;
      if (!inAliases) {
        if (line.trimStart().startsWith("hostname_aliases:")) {
          inAliases = true;
          aliasesIndent = indent;
        }
        continue;
      }
      // Still inside hostname_aliases as long as the indent is deeper
      // than the ``hostname_aliases:`` line itself.
      if (indent <= aliasesIndent) {
        inAliases = false;
        aliasesIndent = -1;
        // Re-evaluate this line at its own indent in case it's a
        // sibling ``spec`` key.
        if (indent === 0) {
          inSpec = line.startsWith("spec:");
        }
        continue;
      }
      const match = line.trimStart().match(/^([^:\s#][^:]*):\s*(.+)$/);
      if (!match) continue;
      const key = match[1].trim();
      // Strip surrounding quotes if YAML quoted the value.
      const value = match[2].trim().replace(/^['"]|['"]$/g, "");
      if (key && value) aliases[key] = value;
    }
    return aliases;
  } catch {
    return {};
  }
}

/**
 * Return the canonical fleet-machine label for THIS host.
 *
 * See module docstring for full resolution order. Env fallbacks are
 * honoured only when the live hostname is empty.
 */
export function resolveHostLabel(opts?: {
  configPath?: string;
  rawHostname?: string;
  env?: NodeJS.ProcessEnv;
}): string {
  const env = opts?.env ?? process.env;
  const rawFull = opts?.rawHostname ?? osHostname() ?? "";
  const raw = (rawFull || "").split(".")[0].trim();
  if (raw) {
    const aliases = loadHostnameAliases(
      opts?.configPath ?? DEFAULT_CONFIG_PATH,
    );
    if (Object.prototype.hasOwnProperty.call(aliases, raw)) {
      return aliases[raw];
    }
    return raw;
  }
  // ``hostname()`` returned empty — only now trust the env overrides.
  return (
    (env.SCITEX_OROCHI_HOSTNAME || "").trim() ||
    (env.SCITEX_OROCHI_MACHINE || "").trim() ||
    (env.SCITEX_AGENT_CONTAINER_HOSTNAME || "").trim() ||
    ""
  );
}
