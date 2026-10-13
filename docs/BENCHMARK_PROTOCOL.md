# One-shot versus feedback: frozen comparison

The primary question is whether measured feedback improves a mesh beyond stopping after its first generation. The one-shot control is exactly the first mesh of the same episode, including the same initial model, geometry, scientific scene, physical inputs and Dict. It is not a deliberately weak geometry-only baseline.

The feedback arm continues from that mesh under the same 2,000,000-cell cap, fixed quality gates and immutable physical contract. It may spend up to five total native attempts, including archived attempts for continuation cases. More attempts necessarily cost more computation: report wall time, attempt count, cell growth and model fees, rather than claiming equal total compute.

Before execution, `portfolio_setup.py` writes a frozen protocol containing core-code and input hashes, budgets, cases, selection rule and metrics. `portfolio_episode.py` refuses changed core code or geometry. No per-case manual parameter changes are made in the experiment driver.

## Cases and boundaries

| Case | Engineering motivation | Representation and scope |
|---|---|---|
| Ahmed 25° | Vehicle base separation and rear wake | Public simplified vehicle with supports; unbounded free-air stress test, no road/moving ground |
| Finite wing | Aircraft wing trailing wake and tip regions | Synthetic closed NACA0012-like wing at 5° incidence; not a production wing or transonic validation |
| Finite cylinder | Wind loading and bluff-body wake, relevant to exposed cylindrical structures | Synthetic finite cylinder; no transient shedding or structural-load accuracy claim |
| Prolate spheroid | Fully immersed streamlined-body boundary layers and wake | Synthetic single-phase submerged body; not a free-surface ship |

These are representative mechanism examples, not a ranking of industrial usage frequency. All shapes had prior development exposure. The car and spheroid reuse two archived V6 attempts and continue for up to three; wing and cylinder have new closed-loop runs on previously used shapes. This is a development evaluation, not a held-out generalisation study.

## Frozen measurements and selection

Primary diagnostic: actual final wall area with at least five native layers, measured using `nSurfaceLayers` and native wall polygon areas. The original 90% coverage gate remains unchanged.

An attempt is admissible for comparison only if native quality, sampled geometry fidelity, scene resolution and cell cap pass, and the native pipeline has no error. Among admissible attempts, choose highest layer coverage, then fewer cells. Keep the original candidate if later interventions worsen it. Show every attempt, including rejected high-coverage meshes. No custom aggregate score is fitted after seeing results.

Also report CheckMesh failure count, non-orthogonality/skewness in raw evidence, actual cells, scenario volume-weighted cell-size statistics, model/fallback decision origins, elapsed time, API fee upper bounds, joint acceptance and screened handoff separately.

Passing layer geometry does not prove true y+, adequate boundary-layer outer thickness, converged force accuracy or mesh independence. A short optional SST flow probe is only a numerical/near-wall sanity screen. Science corridors are hypotheses rather than observed wake trajectories.

## Attribution

`deepseek-flash_initial_plan` and `deepseek-flash` indicate executed model proposals. `deterministic_fallback` indicates a programmed intervention. `geometry_plan` is the deterministic initial meshing plan. The workflow contains all three; improvement of the whole workflow must not automatically be labelled an LLM repair success.

V6 geometry-only/science-prior pairs are a separate ablation. They establish effects of deterministic off-body refinement, not of feedback or LLM reasoning.

## Reproduction

Follow the root README. A fresh reproduction runs full episodes; it cannot reproduce the exact stochastic archived continuation trajectory without its historical records. Published development results identify their code hashes and phases. Model/API snapshots, numerical parallelism and platform versions can affect reruns.

Scientific context: [NASA CFD verification and validation tutorial](https://www.grc.nasa.gov/WWW/wind/valid/tutorial/tutorial.html) separates mesh-related verification from physical validation; [NASA grid convergence guidance](https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html) explains why mesh checks alone do not establish solution accuracy.
