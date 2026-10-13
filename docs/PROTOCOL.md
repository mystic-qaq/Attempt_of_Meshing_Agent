# DrivAer study protocol

The archived study uses original DrivAerML source geometries **1, 318 and 410**. [Input URLs and hashes](../results/drivaer/inputs.json) identify the three files. Entire source triangle sets are retained; a reversible bounding-box-centre translation conditions the coordinates. There is no semantic part deletion or replacement of difficult geometry.

## Physical and resource conditions

|Condition|Setting|
|---|---|
|Environment|Unbounded, incompressible, single-phase external flow|
|Frame|+X inflow, +Z up|
|Speed / kinematic viscosity|30 m/s / 1.5 × 10⁻⁵ m²/s|
|Initial layer request|8 layers; fixed physical first-height estimate|
|Actual cell cap|12,000,000 per native mesh|
|Model actor|`deepseek-flash`|
|API cap|$0.50 per original source across related routes and retries|
|Native backend|OpenFOAM v2412|

The first-height estimate is a planning proxy based on a flat-plate relation, rather than measured wall shear. Source 410's original estimate is approximately 1.296 mm, with an approximately 21.38 mm initial eight-layer stack. Modified layer counts and stack thicknesses require separate reporting.

## Routes and initialization

The programmatic first-output baseline uses geometry, scenario and resource planning without a model. The programmatic feedback route applies predefined snap, refinement and layer recipes. The model route receives native measurements, queries local evidence and proposes bounded actions.

Both feedback routes use the same automatic initial specification. Cached failed baseline records can provide the starting diagnosis; they are not accepted mesh anchors, and their prior native cost remains reportable. When a trial fails, its mesh cannot enter the feasible archive. Without a feasible anchor, a new proposal can return to the shared parameter seed rather than accumulate changes on the failed mesh.

The final paired comparison on source 410 contains three additional full generations per route. The model selected global levels 5, 6 and 5; the programmatic recipes selected level 6 for all three. Attempt caps and cell ceilings were equal, while actual counts and times differed. This comparison does not isolate the model's contribution at fixed resolution.

Development records also include separate snapping and layer-addition stages. Full generation and a substage are different units of computation. The [complete evidence](../results/drivaer/evidence.json) retains every route, including routes that ended without a committed proposal or a new native stage.

## Acceptance and comparison

A research candidate requires verified native quality, accepted boundary topology and sampled fidelity, an accepted scenario screen when present, a positive measured cell count within budget, and no native execution error. Zero basic `checkMesh` failures alone is insufficient.

The scenario screen evaluates specified spatial resolution envelopes; it is not observed flow accuracy. The fidelity observer has limits for highly warped or projected self-crossing polygons. Observation unavailability and proven boundary topology defects are reported separately.

Research eligibility does **not** require 90% five-layer coverage. The stricter layer and estimated y+ flags are separate diagnostics retained in the original records. Their presence in a rejection-reason list must not be confused with the research eligibility predicate in [the implementation](../cfdmesh/drivaer.py).

The declared clear-gain criterion requires a feasible reference and candidate, at least 10 percentage points more actual wall area with ≥5 layers, at most 20% cell growth, and no drop greater than 2 percentage points in ≥1-layer coverage or the three fixed difficult regions. Original layer-target and thickness diagnostics prevent crediting gains obtained only by weakening the layer design. With an infeasible baseline, report repair to feasibility instead of a fictitious gain over a qualified mesh.

## Accounting and interpretation

All related experiments share the source-geometry ledger. Coordinate transformations do not create a new paid case. Settled charges and unresolved request reservations remain visible; conservative ceilings are not provider invoices. An interrupted non-Flash request contributes to accounting but is excluded from Flash performance evidence.

The stored profile label is not proof of the model called: deterministic routes make no model calls. API response records and original-file hashes have separate roles. Archived implementation hashes describe the code used then; repository cleanup does not retrospectively change measurements or imply that the published checkout generated them.

The study is closed. It established no qualified candidate, clear model advantage, validated transferable policy, OPD training result, converged drag, true flow-derived y+, or grid-independent CFD accuracy.
