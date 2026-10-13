"""Paired full-pipeline development experiment, sharing every earlier source expense."""
import argparse
import copy
import os
import subprocess
import sys
from pathlib import Path
from cfdmesh.io import read_json,write_json,code_hash,sha256
from cfdmesh.drivaer import control_actions

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('output');p.add_argument('--code',required=True);p.add_argument('--key-file',required=True)
    p.add_argument('--experience-store');p.add_argument('--model',choices=['deepseek-flash'],default='deepseek-flash')
    p.add_argument('--calibrate-resource',action='store_true',help='freeze same-source pure full baseline cost; native budget gate remains unchanged')
    p.add_argument('--reasoning-effort',choices=['low','high','max'],default='low');p.add_argument('--query-turns',type=int,default=2)
    p.add_argument('--max-output',type=int,default=8192);p.add_argument('--native-stages',type=int,default=4)
    p.add_argument('--arms',nargs='+',choices=['llm','deterministic'],default=['llm','deterministic'])
    p.add_argument('--cases',nargs='+',help='original case IDs; no derived case budget aliases')
    p.add_argument('--decision-checkpoint',help='terminal uncommitted Flash measured-query root, for a single same-source case')
    a=p.parse_args();parent=Path(a.parent).resolve();root=Path(a.output).resolve();code=Path(a.code).resolve()
    if not 1<=a.native_stages<=4 or not 1<=a.query_turns<=6:raise ValueError('invalid declared development allocation')
    protocol=copy.deepcopy(read_json(parent/'protocol.json'))
    if a.cases:
        if not set(a.cases)<=set(c['id'] for c in protocol['cases']):raise ValueError('unknown original case')
        protocol['cases']=[c for c in protocol['cases'] if c['id'] in a.cases]
    if a.decision_checkpoint and len(protocol['cases'])!=1:raise ValueError('checkpoint belongs to one original case')
    if root.exists():raise FileExistsError('new full-pipeline output required')
    for c in protocol['cases']:
        for arm in ('llm','deterministic'):
            previous=read_json(parent/'runs'/f'{c["id"]}_{arm}'/'agent_run.json')
            if previous['status']=='running' and (arm=='llm' or arm in a.arms):
                raise ValueError('do not overlap paid source decisions or continuing control routes')
        baseline=parent.parent/f'program_one_shot_{c["id"].split("_")[-1]}'
        prior=read_json(baseline/'agent_run.json')
        if prior['status']=='running' or prior['source_mutated'] or prior['source_sha256']!=c['source_sha256']:
            raise ValueError('completed immutable source-matched full baseline required')
        c['cached_failure']=str(baseline/'round0/record.json');c['prior_full_baseline_seconds']=prior['seconds']
        if a.calibrate_resource:
            c['resource_baseline']=dict(record=str(baseline/'round0/record.json'),record_sha256=sha256(baseline/'round0/record.json'))
        if a.decision_checkpoint:c['decision_checkpoint']=str(Path(a.decision_checkpoint).resolve())
        if protocol.get('native_mode')=='full':
            old_model=read_json(parent/'runs'/f'{c["id"]}_llm'/'agent_run.json')
            if old_model.get('rounds'):
                c['cached_failure']=str(Path(old_model['rounds'][-1]['native']['case'])/'record.json')
            staged=Path(protocol['previous_staged_campaign'])
            snap_record=staged/'runs'/f'{c["id"]}_llm'/'round0/record.json'
            full_record=baseline/'round0/record.json'
            c['stage_comparison']=dict(snap_record=str(snap_record),snap_record_sha256=sha256(snap_record),
                full_record=str(full_record),full_record_sha256=sha256(full_record))
    protocol.update(code_sha256=code_hash(),native_mode='full',max_native_stages=a.native_stages,
        full_trials_including_cached_baseline=a.native_stages+1,native_subphases_per_full_trial=3,
        study_kind='paired development ablation of coupled full-pipeline exploration; extra native computation reported',
        previous_staged_campaign=protocol.get('previous_staged_campaign',str(parent)),previous_full_campaign=str(parent),
        arms=a.arms,actor_model=a.model,actor_reasoning_effort=a.reasoning_effort,actor_query_turns=a.query_turns,
        episode_seconds=10800,
        deterministic_controls={'full':[control_actions('full',i,calibrated=a.calibrate_resource) for i in range(a.native_stages)]})
    if a.arms!=['llm','deterministic']:
        protocol['study_kind']='additional model development trials; previous controls retained; unequal cumulative compute, no isolated model attribution'
    if a.experience_store:
        snapshot=Path(a.experience_store).resolve();data=read_json(snapshot)
        if {c['source_sha256'] for c in protocol['cases']}&set(data['training_source_groups']):raise ValueError('evaluation leaks into memory')
        protocol.update(experience_store=str(snapshot),experience_store_sha256=sha256(snapshot))
    root.mkdir();(root/'runs').mkdir();(root/'logs').mkdir();write_json(root/'protocol.json',protocol)
    previous_scope=read_json(parent/'api_budget_scope.json') if (parent/'api_budget_scope.json').exists() else {}
    roots=list(dict.fromkeys([*previous_scope.get('run_roots',[]),str(parent/'runs'),str(root/'runs')]))
    shared=dict(run_roots=roots,lock_directory=previous_scope.get('lock_directory',str(parent/'api_case_locks')),source_aliases=previous_scope.get('source_aliases',{}),
        authorization_scope='same original source $0.50 across staged and full ablation; no ledger reset')
    for runs_root in roots:write_json(Path(runs_root).parent/'api_budget_scope.json',shared)
    launch=[]
    for c in protocol['cases']:
        for arm in protocol['arms']:
            name=f'{c["id"]}_{arm}';run=root/'runs'/name;batch=root/'logs'/f'{name}.sbatch'
            batch.write_text(f'''#!/bin/bash
#SBATCH --job-name={name}-full
#SBATCH --partition=C64M256G
#SBATCH --cpus-per-task=32
#SBATCH --time=03:10:00
#SBATCH --output={root}/logs/{name}-%j.log
set -eu
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={code}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd {code}
exec {sys.executable} scripts/drivaer_episode.py {root} {c['id']} {arm}
''')
            if arm=='llm':
                run.mkdir();env=dict(os.environ,PYTHONPATH=str(code),PYTHONDONTWRITEBYTECODE='1')
                with (root/'logs'/f'{name}_advisor.log').open('w') as log:
                    api=subprocess.Popen([sys.executable,'-m','cfdmesh.cli','serve-advisor',str(run),'--key-file',a.key_file,
                        '--usd-limit','.5','--case-usd-limit','.5','--max-calls','40','--max-turns',str(a.query_turns+3),'--query-turns',str(a.query_turns),
                        '--max-output',str(a.max_output),'--reasoning-effort',a.reasoning_effort,'--model',a.model,'--review-policy','program','--seconds','12000'],
                        cwd=code,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
            job=subprocess.check_output(['sbatch','--parsable',str(batch)],text=True,stderr=subprocess.DEVNULL).strip()
            launch.append(dict(case=c['id'],arm=arm,job=job,advisor_pid=api.pid if arm=='llm' else None))
            write_json(root/'launch.json',launch)
    print('paired full trials; jobs',len(launch),flush=True)
