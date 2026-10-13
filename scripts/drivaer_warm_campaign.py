"""A declared development continuation sharing the original $0.50 source cap."""
import argparse
import copy
import os
import subprocess
import sys
from pathlib import Path
from cfdmesh.io import read_json,write_json,code_hash

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('out');p.add_argument('--code',required=True);p.add_argument('--key-file',required=True)
    p.add_argument('--other-budget-root',action='append',default=[])
    p.add_argument('--cached-round',type=int,help='choose a measured failure matching the protected parameter base')
    p.add_argument('--development-extra-stages',type=int,choices=[1,2],help='explicit small development ablation beyond the original six-stage model route; not a matched-budget benchmark')
    a=p.parse_args();parent=Path(a.parent).resolve();out=Path(a.out).resolve();code=Path(a.code).resolve()
    if out.exists():raise FileExistsError('continuation must be fresh')
    protocol=copy.deepcopy(read_json(parent/'protocol.json'));entry=protocol['cases'][0]
    previous=read_json(parent/'runs'/f'{entry["id"]}_llm'/'agent_run.json')
    if previous['status']=='running':raise ValueError('do not interrupt or overwrite a frozen episode')
    cached=a.cached_round if a.cached_round is not None else previous['rounds'][-1]['round']
    entry['cached_failure']=str(parent/'runs'/f'{entry["id"]}_llm'/f'round{cached}'/'record.json')
    out.mkdir();(out/'runs').mkdir();(out/'logs').mkdir()
    prior_stages=len(previous['rounds'])+previous.get('warm_start',{}).get('prior_native_stages',0)
    remaining=6-prior_stages
    if remaining<=0 and not a.development_extra_stages:raise ValueError('original stage allowance exhausted; explicitly declare a development ablation')
    protocol.update(code_sha256=code_hash(),arms=['llm'],max_native_stages=a.development_extra_stages or remaining,
        episode_seconds=6200 if a.development_extra_stages else max(60,int(10800-previous['seconds'])),
        study_kind='development continuation after documented tool faults; not an independent held-out success',
        prior_episode=str(parent),prior_stage_count=prior_stages,
        extra_development_stage_allowance=a.development_extra_stages,
        matched_compute_comparison=not bool(a.development_extra_stages),
        program_feedback_reference=protocol.get('program_feedback_reference',str(parent/'runs'/f'{entry["id"]}_deterministic')),
        initial_spec_origin='archived initial model-derived template; not a pure programmatic one-shot')
    protocol['actor_settings']=dict(max_turns=6,query_turns=2,max_output=8192,reasoning_effort='low',review_policy='program',
        reason='documented long-context/format-review timeout; exact numeric controls retained; native gates unchanged')
    write_json(out/'protocol.json',protocol)
    shared=dict(run_roots=[str(parent/'runs'),str(out/'runs'),*[str(Path(r).resolve()/'runs') for r in a.other_budget_root]],lock_directory=str(parent.parent/'source_budget_locks'),
        source_aliases={},authorization_scope='all versions of this DrivAer focus study share $0.50/source; old ledgers unmodified')
    write_json(parent/'api_budget_scope.json',shared);write_json(out/'api_budget_scope.json',shared)
    for other in a.other_budget_root:write_json(Path(other)/'api_budget_scope.json',shared)
    run=out/'runs'/f'{entry["id"]}_llm';run.mkdir()
    env=dict(os.environ,PYTHONPATH=str(code),PYTHONDONTWRITEBYTECODE='1')
    with (out/'logs/advisor.log').open('w') as log:
        api=subprocess.Popen([sys.executable,'-m','cfdmesh.cli','serve-advisor',str(run),'--key-file',a.key_file,
            '--max-calls','32','--usd-limit','.5','--case-usd-limit','.5','--max-turns','6','--query-turns','2',
            '--max-output','8192','--reasoning-effort','low','--review-policy','program','--seconds','12000'],cwd=code,env=env,stdout=log,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,start_new_session=True)
    batch=out/'logs/run.sbatch'
    batch.write_text(f'''#!/bin/bash
#SBATCH --job-name=drivaer101-warm
#SBATCH --partition=C64M256G
#SBATCH --cpus-per-task=32
#SBATCH --time=03:00:00
#SBATCH --output={out}/logs/native-%j.log
set -eu
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={code}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
exec {sys.executable} {code}/scripts/drivaer_episode.py {out} {entry['id']} llm
''')
    job=subprocess.check_output(['sbatch','--parsable',str(batch)],text=True).strip()
    write_json(out/'launch.json',dict(job=job,advisor_pid=api.pid,source_cap_shared=True));print(job,flush=True)
