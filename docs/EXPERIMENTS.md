# Experiment index

The experiments below used different geometries, code versions and protocols. Their results are retained separately rather than combined into one success rate.

|Study|Question and scope|Evidence|
|---|---|---|
|DrivAer focus, October 2026|Automatic first output, fixed feedback and DeepSeek Flash feedback on original automotive geometry|[Protocol](DRIVAER_FOCUS.zh-CN.md), [final interpretation](../results/drivaer_focus_20261012/FINAL_CONCLUSION.zh-CN.md), [all-stage records](../results/drivaer_focus_20261012/FINAL_EVIDENCE.json)|
|Final paired full generation|Three additional trials per route, shared automatic seed and resource calibration|[All six meshes](../results/drivaer_focus_20261012/FINAL_FLASH_113.zh-CN.md)|
|Earlier focused development|Separate snap trials and coupled full-pipeline trials, including failed decisions|[Stage trials](../results/drivaer_focus_20261012/STAGED_CGAL_RESULTS.zh-CN.md), [full trials](../results/drivaer_focus_20261012/FULL_PIPELINE_106.zh-CN.md)|
|Initial DrivAer comparison|Five Agent and five direct Codex trials; differing action spaces and cell counts|[Protocol](DRIVAER_PROTOCOL.zh-CN.md), [ten attempts](../results/drivaer_20261011/REPORT.zh-CN.md)|
|Subsequent DrivAer feedback|Five trials with a historical initial specification and marked fallbacks|[Results](../results/drivaer_v9_20261012/REPORT.zh-CN.md)|
|Simplified external-flow cases|Geometry/scenario mechanisms and one-shot versus feedback; not a held-out automotive evaluation|[Measured results](RESULTS.md), [historical protocol](BENCHMARK_PROTOCOL.md), [separate proposal validation](RESULTS_APPENDIX.md)|
|Tool integration|Synthetic gap and stage execution checks|[Gap integration](../results/mechanisms_20261012/README.md), [planner audit](../results/mechanisms_20261012/PLANNER_AUDIT.md)|

## Interpretation

Layer coverage is measured by actual wall area and native layer fields. Requested layer count is not actual coverage. A high-coverage rejected mesh does not become a feasible candidate.

The focused study's research acceptance combines native quality, topology, fidelity, scenario and resource requirements. Its older production-layer marker is separate. Observer unavailability, proven quality defects and budget rejection have distinct meanings.

The final programmatic feedback route globally refined the common parameter seed. Its roughly four-million-cell meshes are not the programmatic first output, which had 1,361,838 cells. Attempt limits, actual cell counts, elapsed time and API fees are reported independently.

Historical hashes identify the code and records used at execution time. The published source is a later snapshot, and editorial/path transformations are documented in [snapshot provenance](CODE_PROVENANCE.json). Raw geometries and complete native meshes are not included.
