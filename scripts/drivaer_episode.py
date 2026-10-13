"""Run one arm from a frozen research protocol, without task-specific manual Dict edits."""
import argparse
from pathlib import Path
from cfdmesh.drivaer import run_drivaer
from cfdmesh.io import read_json, code_hash, sha256

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('experiment');parser.add_argument('case');parser.add_argument('arm',choices=['llm','deterministic'])
    parser.add_argument('--of-root',default=str(Path.home()/'.conda-envs/openfoam2412'))
    args=parser.parse_args();root=Path(args.experiment);protocol=read_json(root/'protocol.json')
    if protocol['code_sha256']!=code_hash():raise ValueError('implementation changed after protocol freeze')
    entry=next(c for c in protocol['cases'] if c['id']==args.case)
    if entry.get('initial_spec_sha256') and sha256(entry['initial_spec'])!=entry['initial_spec_sha256']:
        raise ValueError('frozen initial specification changed')
    validator=protocol.get('independent_validator')
    if validator and sha256(validator['executable'])!=validator['executable_sha256']:raise ValueError('frozen independent geometry validator changed')
    if protocol.get('experience_store') and sha256(protocol['experience_store'])!=protocol['experience_store_sha256']:
        raise ValueError('frozen training experience snapshot changed')
    if sha256(entry['source'])!=entry['source_sha256']:raise ValueError('source geometry changed')
    run=run_drivaer(entry['source'],root/'runs'/f'{args.case}_{args.arm}',args.of_root,arm=args.arm,
        budget=protocol['cell_cap'],max_stages=protocol['max_native_stages'],n_procs=protocol['mpi_processes'],
        round_seconds=protocol['stage_seconds'],total_seconds=protocol['episode_seconds'],
        initial_spec=read_json(entry['initial_spec']) if entry.get('initial_spec') else None,
        scenario_context=protocol.get('scenario_context'),cached_failure=entry.get('cached_failure') if args.arm=='llm' or protocol.get('native_mode')=='full' else None,
        experience_store=protocol.get('experience_store') if args.arm=='llm' else None,
        original_source_sha256=entry.get('original_source_sha256'),geometry_route=entry.get('geometry_route','original triangles'),
        cgal_validator=validator['executable'] if validator else None,native_mode=protocol.get('native_mode','staged'),
        actor_model=protocol.get('actor_model','deepseek-flash'),stage_comparison=entry.get('stage_comparison'),resource_baseline=entry.get('resource_baseline'),decision_checkpoint=entry.get('decision_checkpoint'))
    print(run['status'],run.get('stop_reason'),flush=True)
    raise SystemExit(0 if run['status'] in ('completed','failed') else 2)
