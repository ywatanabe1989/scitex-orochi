"""State definition modules — Layer B of the state pipeline.

Each module exports a pure ``derive_<name>(observations) -> dict`` function
that maps Layer-A primitive observations to a labelled, evidence-bearing,
versioned verdict:

    {"label": str, "evidence": str, "orochi_version": str}

Multiple state schemes coexist by sitting beside each other here. Adding
a new scheme is "drop a new file" — no edits to the collector or to
existing schemes. Versioning is per-scheme so consumers can pin to a
specific scheme orochi_version when behaviour changes.
"""
