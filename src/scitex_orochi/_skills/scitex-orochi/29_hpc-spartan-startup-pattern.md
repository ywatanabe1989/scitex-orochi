---
name: orochi-spartan-hpc-startup-pattern
description: Canonical startup pattern for Spartan (and other Lmod/module-based HPC clusters) — module load chain, LD_LIBRARY_PATH hardening for non-interactive SSH, login-node vs compute-node divergence, and avoiding multi-second bash-startup latency. Codified from 2026-04-13 head-<host> fixes (todo#307).
---

# Spartan / HPC Startup Pattern

What every agent running on Spartan (or any Lmod-based HPC cluster) must do at shell startup, and what every *remote* tool invoking Spartan must *not* assume about the target shell's state.

This skill codifies the pattern that was reconstructed over several incidents on 2026-04-13 (non-interactive `pip3.11` missing `libpython3.11.so.1.0`, `squeue` missing from PATH in probes, bash startup ballooning to ~2.7 s on login nodes, and the on-going login1 controller-only policy).

## Why HPC is different

Unlike a normal Linux host, an HPC login node gives you almost nothing by default:

- `$PATH` does **not** include compiler toolchains, Python, CUDA, Apptainer, Node — none of them. You get them by running `module load <name>`.
- `$LD_LIBRARY_PATH` does not include shared libraries from modules — `module load` sets it, but only for the current shell.
- `module` itself is a shell function injected by Lmod's init script. Non-interactive shells (`ssh host 'cmd'`) often do **not** source that init, so `module` doesn't exist and every downstream assumption collapses.
- User quotas on login1 are shared and visible to sysadmins. Anything that runs every 60 s across a fleet of agents is noticed; anything that runs every 5 s is yelled at.

Pragmatically this means an HPC startup has three phases:

1. **Detect whether we're on the cluster at all** (hostname check).
2. **Load modules and export shared-lib paths** — but only if we're actually on login node / compute node, never on non-HPC hosts that happen to source the same dotfiles.
3. **Decide login vs compute semantics** — login1 is controller-only (see `project_spartan_login_node` memory); compute nodes do the actual work.

## Canonical dotfiles snippet

Reference implementation lives in `~/.dotfiles/src/.bash.d/secrets/999_unimelb_spartan.src` (path is under `secrets/` for legacy reasons; the file itself holds no secrets). Essentials:

```bash
has_module_command() { command -v module &>/dev/null; }

_spartan_load_module_if_not_loaded() {
    has_module_command || return 1
    module is-loaded "$1" || module load "$1" || return 1
}

spartan_load_modules() {
    has_module_command || return 1
    # Lmod aborts the whole chain on an unknown module — keep known-good names grouped,
    # and load volatile names (slurm/*) separately with error suppression.
    module load \
        GCCcore/11.3.0 \
        Python/3.11.3 \
        OpenSSL/1.1 \
        Apptainer/1.3.3 \
        bzip2 \
        GLib/2.72.1 \
        GTK3/3.24.33 \
        Gdk-Pixbuf/2.42.8 \
        nodejs/20.13.1 \
        Pandoc/3.1.2
    module load slurm/default 2>/dev/null \
        || module load slurm/latest 2>/dev/null \
        || true
}

# Ensure Python 3.11 shared libs are findable even in non-interactive / agent SSH
# sessions — pip3.11 fails with libpython3.11.so.1.0 not found when modules are not loaded.
_SPARTAN_PY311_LIB="/apps/easybuild-2022/easybuild/software/Compiler/GCCcore/11.3.0/Python/3.11.3/lib"
if [[ $(hostname) == *"spartan"* ]] && [ -d "$_SPARTAN_PY311_LIB" ]; then
    export LD_LIBRARY_PATH="${_SPARTAN_PY311_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
unset _SPARTAN_PY311_LIB
```

Three invariants this snippet enforces:

1. **Hostname guard** (`[[ $(hostname) == *spartan* ]]`) prevents non-Spartan hosts (non-HPC hosts) that sync the same dotfiles from accidentally exporting a Linux-only library path.
2. **Directory guard** (`[ -d "$_SPARTAN_PY311_LIB" ]`) tolerates the path being moved by a future EasyBuild upgrade — the snippet simply no-ops instead of breaking.
3. **LD_LIBRARY_PATH is exported unconditionally on Spartan**, not gated on `has_module_command`, because non-interactive SSH sessions (where `module` is not available) are exactly the case where `pip3.11` needs the hardcoded fallback.

## Continued in

- [`66_hpc-spartan-startup-pattern-extras.md`](66_hpc-spartan-startup-pattern-extras.md)
