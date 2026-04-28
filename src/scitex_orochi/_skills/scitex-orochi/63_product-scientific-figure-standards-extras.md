---
name: orochi-scientific-figure-standards-part-2
description: Fleet-wide standards for scientific figures and statistics — sample size disclosure, H₀ mandatory, mean±SD shading, null controls, event annotations, per-subject summary lines, and per-patient PDF layout. Consolidates ywatanabe guidance from 2026-04-13 neurovista review. (Part 2 of 2 — split from 42_product-scientific-figure-standards.md.)
---

> Part 2 of 2. See [`42_product-scientific-figure-standards.md`](42_product-scientific-figure-standards.md) for the orchestrator/overview.
## 5. Deliverable structure — per-subject + grand summary

msg #8592/#8593: *"全被験者バージョンで"* + *"二枚目にグランドサマリーを入れて"*.

- **Page 1: per-subject panels** (one subject per panel or one subject per row), with shared axes so the reader can eye-compare.
- **Page 2: grand summary** — cross-subject aggregate + the §6 stats block + effect sizes. One page the PI can read in 90 seconds.
- **Pages 3..N: per-patient detail** pages when the per-subject panels on page 1 are too dense; otherwise omit.
- **Consistent axes** across all pages. No per-page auto-scaling unless the page explicitly flags it.
- **Page footer**: commit hash of the analysis code, data cutoff timestamp, author agent name, figure generation timestamp. Reproducibility provenance lives on the page, not in a separate lab notebook.

## 6. Statistical test reporting block — H₀ mandatory, H₁ when defined

msg #8596: *"統計検定には必ず null hypothesis を書いてください。"*
msg #8599: *"H0 としてくれればいいですね。うんうん。H1 もあれば"*

Every statistical claim (every p-value, every "significant difference", every "no difference") must state the following **inline in the caption or figure annotation**:

| Field | Example | Requirement |
|---|---|---|
| **H₀** | "feature X pre-ictal mean = inter-ictal mean" | **Mandatory.** "No difference" is not a hypothesis — state the equality explicitly. |
| **H₁** | "feature X pre-ictal mean > inter-ictal mean" | **Include when defined.** One-sided vs two-sided is decided *before* seeing the data. |
| **Test** | "paired Wilcoxon signed-rank" | Parametric/non-parametric, paired/unpaired. |
| **α** | "0.05" | Default 0.05; state it. |
| **Correction** | "Benjamini-Hochberg, 127 comparisons" | Method and family size. |
| **Effect size** | "Cliff's δ = 0.34 [95% CI 0.21, 0.48]" | **Required.** p-values are not effect sizes. |
| **Null control** | "shuffled labels, 1000 permutations" | Required for time-locked / condition-locked claims. |

A claim that can't fill this block is not yet ready to be published.

## 7. Null / sanity controls — watch the FDR floor

msg #8550 (implied): a grand summary showed 18–25% of features "significant" under a shuffled-label null — i.e. the null is already noisy at the FDR floor. Rules:

- Every condition plot needs a **label-shuffled control** on the same axes as the real data so readers can eyeball the effect size.
- If the null control itself fires above the nominal FDR, the methodology has a bug **or** the test family is not independent — investigate before claiming any real effect. A real effect at 40% significant and a null at 25% significant is not a real effect.
- Classifier "chance level" lines must come from a permutation null, not a theoretical `1/K`, unless the sampler is exactly balanced and the prior is flat.
- Figures with no null control are preliminary; label them as such in the title.

## 8. Anti-patterns (hard rejects when shared with collaborators)

Context: deliverables in this channel are shared with David-sensei and Yanagisawa-sensei (msg #8556). Paper-level quality is the bar; lab-internal shortcuts are not acceptable.

- **"Representative example"** without a selection criterion. State the criterion or replace with a random draw + null.
- **Bar charts without overlaid dots** for `n < 50` — bars hide bimodality and outliers.
- **Dual-axis line plots** with independently-rescaled axes. Split into stacked subplots instead.
- **`jet` / `hsv` colormaps** — perceptually non-uniform. Use `viridis`, `cividis`, `magma`, or a named diverging map.
- **"p < 0.05"** as the only statistic. See §6.
- **"Trend toward significance"** — it either crossed α or it didn't.
- **Silent time-axis rounding** — see §2.
- **Duplicate panels** — see §2.
- **Manual Photoshop touch-ups** — the figure must be regenerable end-to-end from code.

## 9. Tooling

- `scitex-python` plotting utilities should emit figures that satisfy §1–§3 by default. Gaps are scitex-python bugs — file them.
- PDF generation goes through one pipeline, no hand edits.
- Figure scripts live under `scripts/` (SciTeX convention), output under `./data/` or `./figures/`, never into the repo root.
- Commit hash for the footer comes from `git rev-parse --short HEAD` at generation time.

## Related

- memory `feedback_visibility_is_existence.md` — UI / screenshot as first-class deliverable
- `fleet-communication-discipline.md` — how to report scientific findings to ywatanabe
- `scitex-python` plotting module — implementation home for the defaults described here
- (future) `reference_neurovista_review_protocol.md` — end-to-end review workflow

## Change log

- **2026-04-13 (initial + verified)**: Drafted from general principles, then reconciled against ywatanabe msgs #8550/#8556/#8557/#8592/#8593/#8594/#8596/#8599/#8607/#8611/#8613 pasted in #agent #8618. Added §0 meta rule, §2 aligned-subplots + duplicate-panels + time-axis, §3 per-subject aligned windows + bimodality heatmap note, §4 event annotations (red line at `t=0`, remove 1h/24h reference lines), §5 per-subject + grand summary page layout, §6 H₀ mandatory + H₁ when defined, §7 FDR-floor rule from msg#8550 grand summary. Author: mamba-skill-manager.
