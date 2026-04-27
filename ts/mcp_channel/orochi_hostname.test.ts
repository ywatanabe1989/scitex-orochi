/**
 * Regression tests for ``resolveHostLabel`` — the TS client-side host
 * identity resolver.
 *
 * Two incidents shape these tests:
 *
 *   1. Lead msg#15578 — proj-neurovista displayed as mba on spartan
 *      because env vars beat ``orochi_hostname()``. PR#309 flipped the
 *      priority so ``orochi_hostname()`` wins.
 *   2. ywatanabe msg#16102 — mba host displayed as the raw
 *      ``Yusukes-MacBook-Air`` on the Agents dashboard because PR#309
 *      skipped the ``hostname_aliases`` map that used to translate
 *      ``Yusukes-MacBook-Air`` → ``mba``. The follow-up fix restores
 *      alias application before the raw-orochi_hostname fallback.
 *
 * Final resolution order (first non-empty wins):
 *   1. ``hostname_aliases[orochi_hostname()]`` from shared/config.yaml.
 *   2. Raw short ``orochi_hostname()``.
 *   3. Env fallback (``SCITEX_OROCHI_HOSTNAME`` /
 *      ``SCITEX_OROCHI_MACHINE`` /
 *      ``SCITEX_AGENT_CONTAINER_HOSTNAME``) — only when
 *      ``orochi_hostname()`` returns empty.
 *
 * Run with ``bun test ts/mcp_channel/orochi_hostname.test.ts``.
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { writeFileSync, mkdtempSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

import { resolveHostLabel, loadHostnameAliases } from "./orochi_hostname";

let tmpConfigDir: string;
let tmpConfigPath: string;

const ENV_KEYS = [
  "SCITEX_OROCHI_HOSTNAME",
  "SCITEX_OROCHI_MACHINE",
  "SCITEX_AGENT_CONTAINER_HOSTNAME",
];
let _savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  tmpConfigDir = mkdtempSync(join(tmpdir(), "orochi-orochi_hostname-test-"));
  tmpConfigPath = join(tmpConfigDir, "config.yaml");
  _savedEnv = {};
  for (const k of ENV_KEYS) {
    _savedEnv[k] = process.env[k];
    delete process.env[k];
  }
});

afterEach(() => {
  for (const k of ENV_KEYS) {
    if (_savedEnv[k] === undefined) {
      delete process.env[k];
    } else {
      process.env[k] = _savedEnv[k];
    }
  }
  try {
    rmSync(tmpConfigDir, { recursive: true, force: true });
  } catch {}
});

function writeConfig(body: string): void {
  writeFileSync(tmpConfigPath, body, "utf-8");
}

const SAMPLE_ALIASES_YAML = `
apiVersion: scitex-orochi/v1
kind: Config
metadata:
  orochi_machine: ywata-note-win
spec:
  hub:
    hosts: [192.168.11.22, scitex-orochi.com]
    port: 8559
  hostname_aliases:
    Yusukes-MacBook-Air: mba
    DXP480TPLUS-994: nas
    spartan-login1: spartan
    # ywata-note-win: identity, no entry needed
`;

describe("loadHostnameAliases", () => {
  test("parses the documented alias entries", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const aliases = loadHostnameAliases(tmpConfigPath);
    expect(aliases).toEqual({
      "Yusukes-MacBook-Air": "mba",
      "DXP480TPLUS-994": "nas",
      "spartan-login1": "spartan",
    });
  });

  test("returns empty dict when config file is missing", () => {
    expect(loadHostnameAliases(join(tmpConfigDir, "missing.yaml"))).toEqual({});
  });

  test("returns empty dict when hostname_aliases section is absent", () => {
    writeConfig("apiVersion: scitex-orochi/v1\nspec:\n  hub:\n    port: 8559\n");
    expect(loadHostnameAliases(tmpConfigPath)).toEqual({});
  });

  test("ignores inline comments and preserves multi-host values", () => {
    writeConfig(
      "spec:\n" +
        "  hostname_aliases:\n" +
        "    Yusukes-MacBook-Air: mba   # mba host\n" +
        "    DXP480TPLUS-994: nas\n",
    );
    expect(loadHostnameAliases(tmpConfigPath)).toEqual({
      "Yusukes-MacBook-Air": "mba",
      "DXP480TPLUS-994": "nas",
    });
  });
});

describe("resolveHostLabel", () => {
  test("returns raw orochi_hostname when no alias entry and no env", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const result = resolveHostLabel({
      configPath: tmpConfigPath,
      rawHostname: "ywata-note-win",
    });
    expect(result).toBe("ywata-note-win");
  });

  test("applies alias map to translate Yusukes-MacBook-Air -> mba (msg#16102)", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const result = resolveHostLabel({
      configPath: tmpConfigPath,
      rawHostname: "Yusukes-MacBook-Air",
    });
    expect(result).toBe("mba");
  });

  test("alias map wins over env var when both are present", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const result = resolveHostLabel({
      configPath: tmpConfigPath,
      rawHostname: "Yusukes-MacBook-Air",
      env: { SCITEX_OROCHI_HOSTNAME: "totally-wrong" } as NodeJS.ProcessEnv,
    });
    expect(result).toBe("mba");
  });

  test("env var ignored when live orochi_hostname is populated (msg#15578 regression)", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const result = resolveHostLabel({
      configPath: tmpConfigPath,
      rawHostname: "spartan-login1",
      env: { SCITEX_OROCHI_HOSTNAME: "mba" } as NodeJS.ProcessEnv,
    });
    // Alias applies first — spartan-login1 -> spartan. The stale mba
    // env var does NOT leak in.
    expect(result).toBe("spartan");
  });

  test("FQDN reduced to the short-form orochi_hostname before lookup", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const result = resolveHostLabel({
      configPath: tmpConfigPath,
      rawHostname: "spartan-login1.hpc.unimelb.edu.au",
    });
    expect(result).toBe("spartan");
  });

  test("env fallback honoured only when orochi_hostname is empty", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    const result = resolveHostLabel({
      configPath: tmpConfigPath,
      rawHostname: "",
      env: { SCITEX_OROCHI_HOSTNAME: "container-host" } as NodeJS.ProcessEnv,
    });
    expect(result).toBe("container-host");
  });

  test("env fallback covers all three documented env vars", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    // Only SCITEX_AGENT_CONTAINER_HOSTNAME set.
    expect(
      resolveHostLabel({
        configPath: tmpConfigPath,
        rawHostname: "",
        env: {
          SCITEX_AGENT_CONTAINER_HOSTNAME: "container-host",
        } as NodeJS.ProcessEnv,
      }),
    ).toBe("container-host");
    // MACHINE beats AGENT_CONTAINER_HOSTNAME.
    expect(
      resolveHostLabel({
        configPath: tmpConfigPath,
        rawHostname: "",
        env: {
          SCITEX_AGENT_CONTAINER_HOSTNAME: "container-host",
          SCITEX_OROCHI_MACHINE: "orochi_machine-env",
        } as NodeJS.ProcessEnv,
      }),
    ).toBe("orochi_machine-env");
    // HOSTNAME beats MACHINE.
    expect(
      resolveHostLabel({
        configPath: tmpConfigPath,
        rawHostname: "",
        env: {
          SCITEX_AGENT_CONTAINER_HOSTNAME: "container-host",
          SCITEX_OROCHI_MACHINE: "orochi_machine-env",
          SCITEX_OROCHI_HOSTNAME: "orochi_hostname-env",
        } as NodeJS.ProcessEnv,
      }),
    ).toBe("orochi_hostname-env");
  });

  test("returns empty string when orochi_hostname is empty and no env set", () => {
    writeConfig(SAMPLE_ALIASES_YAML);
    expect(
      resolveHostLabel({
        configPath: tmpConfigPath,
        rawHostname: "",
        env: {} as NodeJS.ProcessEnv,
      }),
    ).toBe("");
  });

  test("raw orochi_hostname returned verbatim when config.yaml is missing", () => {
    const result = resolveHostLabel({
      configPath: join(tmpConfigDir, "missing.yaml"),
      rawHostname: "Yusukes-MacBook-Air",
    });
    // No alias map available → raw orochi_hostname verbatim.
    expect(result).toBe("Yusukes-MacBook-Air");
  });
});
