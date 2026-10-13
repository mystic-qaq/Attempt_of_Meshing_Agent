# Running a DrivAer case

The archived experiments are closed. The commands below are explicit entry points for a separately provisioned Linux environment. Installation and software tests do not start native meshing or model inference.

## Environment

Use Python 3.11, OpenFOAM v2412 and a compatible MPI installation. Set `OF_ROOT` to the OpenFOAM installation containing `bin/` and `etc/`. Install the package from the repository root:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m scripts.audit_repository
```

[requirements-native.txt](../requirements-native.txt) records the Python versions used in the native-analysis environment. It does not install OpenFOAM or MPI. The optional [CGAL build script](../scripts/build_cgal_audit.sh) requires separately installed CGAL and Boost development dependencies.

Obtain an original DrivAerML STL using [the input references](../results/drivaer/inputs.json). Supply metre units, +X inflow and +Z up. Raw geometry is not included in this repository.

## Prepare and freeze

From the repository root, choose fresh output directories outside the checkout:

```bash
python -m scripts.drivaer_prepare /work/drivaer/preparation \
  --of-root "$OF_ROOT" --source /data/drivaer_410.stl
python -m scripts.freeze_drivaer /work/drivaer/preparation /work/drivaer/experiment \
  --mode full --stages 4 --processes 32
```

Preparation audits the source, constructs an automatic seed and performs a native integration check on a synthetic fixture. It consumes native computation. Add `--cgal-validator /path/to/cgal_surface_audit` to preparation to retain the independent input certificate. The freezer checks completed preparation, binds source and parameter hashes, and creates a paired protocol; it launches no jobs.

The four-stage full mode starts each route with a programmatic generation and allows up to three subsequent feedback generations. It is a convenience entry point for a new experiment, not a byte-identical reconstruction of the final archived comparison, which reused measured failed baseline records and resource calibration. Archived record hashes describe the historical executions.

Related experiments in the same source-budget scope must pass `--history /work/drivaer/previous_experiment` when freezing. Share the original source ledger across retries; do not create a new budget by renaming a case or moving coordinates.

## Execute explicitly

The deterministic route needs no API key:

```bash
python -m scripts.drivaer_episode /work/drivaer/experiment drivaer_410 deterministic \
  --of-root "$OF_ROOT"
```

For the model route, run the advisor in one terminal and the episode in another. The advisor waits for measured requests and is fixed to DeepSeek Flash:

```bash
cfdmesh serve-advisor /work/drivaer/experiment/runs/drivaer_410_llm \
  --key-file /private/deepseek.key --model deepseek-flash \
  --usd-limit 0.50 --case-usd-limit 0.50 --max-calls 40 \
  --query-turns 2 --max-turns 5 --max-output 8192 \
  --reasoning-effort low --review-policy program --seconds 12000
```

```bash
python -m scripts.drivaer_episode /work/drivaer/experiment drivaer_410 llm \
  --of-root "$OF_ROOT"
```

This route performs paid API calls when requests arrive. The shared ceiling includes reservations and retries. Native stage count, native wall time and measured cells are separate limits. No key belongs in source control or experiment reports.

## Inspect outcomes

```bash
python -m scripts.drivaer_report /work/drivaer/experiment /work/drivaer/report
```

The report retains all stages and refuses unfinished episodes as final results. Inspect `agent_run.json`, stage records, native logs and the feasible archive. The episode command returns successfully for a recorded completed or failed experiment; its process exit status alone does not mean the mesh passed. Read `research_eligible` and the rejection evidence.

The checked-in [measurement collection](../results/drivaer/evidence.json) is sufficient to inspect the reported counts and failures. Full specifications, raw native artifacts and executable environment paths remain in the original experiment archive, so the compact collection alone cannot reproduce a historical mesh byte-for-byte.

To render an explicitly chosen recorded stage when its native mesh is available:

```bash
python -m scripts.drivaer_visualize /work/drivaer/report/comparison.json /work/drivaer/figures \
  --case drivaer_410 --arm llm --round 1
```

The stage index is zero-based. Rejected stages keep their rejection label; figures cannot certify topology.
