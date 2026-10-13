# Attribution and licensing

## Code

Project code is GPL-3.0-only; see [LICENSE](LICENSE). OpenFOAM v2412 is an external native backend and is not bundled. Its tutorial dictionaries are read from the user's installation. Optional generated native instrumentation retains the upstream GPL notices; it was not used in the recorded study.

The optional CGAL surface-audit source is GPL-3.0-only. CGAL, Boost, GMP, MPFR and compiled binaries are separate dependencies. A source-geometry certificate does not establish final volume-mesh quality.

## DrivAerML data and figures

The study uses geometries 1, 318 and 410 from [neashton/DrivAerML](https://huggingface.co/datasets/neashton/drivaerml). Attribution: Ashton et al., *DrivAerML: High-Fidelity Computational Fluid Dynamics Dataset for Road-Car External Aerodynamics*, [arXiv:2408.11969](https://arxiv.org/abs/2408.11969). Dataset licensing is CC-BY-SA-4.0, as recorded in [the input provenance](results/drivaer/inputs.json).

The four figures under `results/drivaer/figures/` derive from these geometries and actual OpenFOAM mesh fields. They retain [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/) attribution separately from the code. They depict rejected diagnostic meshes and do not certify simulation accuracy. Raw STL files and complete derived meshes are not distributed here.

## Measurement records

[The measurement collection](results/drivaer/evidence.json) retains source identity, numerical results, failure reasons, timings, cost ceilings and original-record hashes. Original environment paths and private provider reasoning are omitted. Internal record identifiers are preserved for traceability and are not release names. [The manifest](results/drivaer/manifest.json) identifies the published data and figures by SHA256.

Credentials, original CAD/STL, native volume meshes and account-specific paths are outside the publication boundary.
