"""Execute one frozen case. Never tune case-specific parameters in this driver."""
import argparse
from pathlib import Path
from cfdmesh.agent import run_agent
from cfdmesh.io import read_json, sha256, code_hash

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('root'); p.add_argument('case')
    p.add_argument('--of-root', default=str(Path.home() / '.conda-envs/openfoam2412'))
    args = p.parse_args(); root = Path(args.root)
    protocol = read_json(root / 'portfolio_protocol.json')
    entry = next(e for e in protocol['cases'] if e['id'] == args.case)
    if code_hash() != protocol['code_sha256']: raise ValueError('core changed after protocol freeze')
    if sha256(entry['source']) != entry['source_sha256']: raise ValueError('source changed after protocol freeze')
    flow = dict(speed=30., nu=1.5e-5, yplus=50., layers=8)
    if entry['family'] == 'submerged_body': flow.update(speed=2., nu=1e-6)
    run = run_agent(entry['source'], root / 'runs' / args.case, args.of_root,
                    budget=protocol['cell_cap'], max_rounds=entry['new_mesh_attempt_limit'],
                    n_procs=protocol['mpi_processes'], advisor='deepseek-flash',
                    round_seconds=protocol['per_round_seconds'], total_seconds=protocol['new_episode_seconds'],
                    require_layers=True, flow=flow, flow_probe=True, model_plan=True,
                    resume_from=entry['parent'], scenario_context=read_json(entry['scenario_file']))
    print(args.case, run['status'], run.get('stop_reason'), flush=True)
    # A rejected mesh is a completed scientific experiment, not a driver crash.
    raise SystemExit(0 if run['status'] in ('completed', 'failed', 'blocked') else 2)
