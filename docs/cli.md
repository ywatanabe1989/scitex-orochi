# scitex-orochi CLI Convention

This is a short, web-discoverable pointer to the canonical CLI convention
document.

**Canonical location**:
[`src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`](../src/scitex_orochi/_skills/scitex-orochi/convention-cli.md)

The canonical file is loaded by the skill system at agent boot and is the
single source of truth for:

- The `scitex-orochi <noun> <verb>` canonical command shape
- The complete registry of noun groups (`agent`, `channel`, `workspace`,
  `invite`, `message`, `orochi_machine`, `cron`, `disk`, `host-liveness`,
  `hungry-signal`, `chrome-watchdog`, `dispatch`, `todo`, `push`,
  `server`, `config`, `system`, `auth`, `hook`, `host-identity`)
- The deprecation policy (hard-error on rename, soft one-time-per-shell
  notes, `SCITEX_OROCHI_NO_DEPRECATION=1` opt-out)
- The list of flat keepers (only `-h/--help`, `--help-recursive`,
  `--orochi_version`, `--json`, `mcp start`)
- The `(Available Now)` help-suffix rendering rule
- Standard flags, exit codes, stdout/stderr discipline

## Why two files?

The `_skills/` path is consumed by the in-agent skill loader. The `docs/`
path is consumed by GitHub's repo-level file browser and
`readthedocs`-style consumers. Two discovery paths, one source of truth.

Per decision Q3 of plan PR #337, only the `_skills/` file may be edited.
This file is a permanent pointer — do not duplicate content here.

## Related

- Refactor plan: [`cli-refactor-plan-2026-04-22.md`](cli-refactor-plan-2026-04-22.md)
  (PR #337, merged)
- Skill index: [`../src/scitex_orochi/_skills/SKILL_INDEX.md`](../src/scitex_orochi/_skills/SKILL_INDEX.md)
- Help-availability implementation:
  `../src/scitex_orochi/_cli/_help_availability.py`
- Deprecation helper:
  `../src/scitex_orochi/_cli/_deprecation.py`
