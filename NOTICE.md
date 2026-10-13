# Attribution and publication scope

- OpenFOAM v2412 is the native backend, not bundled. Tutorial dictionaries are read from the user's installation. Optional generated native instrumentation preserves original GPL notices; it is off and unused in these experiments.
- Ahmed 25°: [Nathan Rooy's ahmed-bluff-body-cfd](https://github.com/nathanrooy/ahmed-bluff-body-cfd/blob/master/geometry/ahmed_25deg_m.stl). No source redistribution licence was verified. Its STL and derived full mesh/body exports are excluded. Attributed screenshots and measurements document private evaluation.
- Cylinder, finite wing and prolate spheroid: project-generated canonical probes. Scripts describe their construction; these are not production designs.
- Historical NASA/DrivAer/AhmedML preparation records are excluded from the curated export. Eligibility failures are discussed without bundling sources.
- The DrivAer-focused study uses [neashton/DrivAerML](https://huggingface.co/datasets/neashton/DrivAerML), licensed CC-BY-SA-4.0. Source identifiers, download URLs and original hashes are recorded in `results/drivaer_focus_20261012/input_provenance.json`. Raw STL and full derived meshes are excluded. DrivAer mesh figures are derived visualizations of this dataset, attributed to its creators through the dataset and [paper](https://arxiv.org/abs/2408.11969); these figures retain CC-BY-SA-4.0 separately from the GPL code. Invalid meshes are labelled rejected diagnostics.
- Optional CGAL 5.6.2 audit/wrap sources are GPL-3.0-only; CGAL and Boost dependencies and binaries are not bundled. Independent wrapping does not imply acceptable geometry fidelity.
- API keys, original CAD/STL, native polyMesh, provider internal reasoning and account-specific paths are excluded. Sanitised evidence is explicitly marked and linked to original-file hashes.

Copyright (C) 2026 CFD Meshing Agent contributors. Code is GPL-3.0-only. See LICENSE.
