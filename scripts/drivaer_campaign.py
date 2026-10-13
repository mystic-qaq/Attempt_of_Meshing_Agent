"""Freeze and launch paired DrivAer episodes on the existing Slurm installation."""
import argparse
import os
import subprocess
import sys
from pathlib import Path
from cfdmesh.io import read_json,write_json,code_hash,sha256
from cfdmesh.drivaer import PROFILE,control_actions

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('preparation');p.add_argument('experiment')
    p.add_argument('--key-file',required=True);p.add_argument('--code',required=True)
    p.add_argument('--experience-store',help='immutable training-case memory snapshot; supplied only to the model route')
    a=p.parse_args();prep=Path(a.preparation).resolve();root=Path(a.experiment).resolve();code=Path(a.code).resolve()
    if root.exists():raise FileExistsError('campaign output must be fresh')
    data=read_json(prep/'preparation.json');smoke=data['smoke']
    if not smoke.get('snap_accepted') or not smoke.get('layer_native_complete') or smoke.get('source_mutated') is not False:
        raise ValueError('native stage integration has not passed')
    root.mkdir();(root/'runs').mkdir();(root/'logs').mkdir()
    cases=[];excluded=[]
    for i,entry in enumerate(data['inputs']):
        if entry.get('error') or not entry.get('native',{}).get('accepted'):
            excluded.append(entry);continue
        legacy=entry.get('legacy_seed_certification')
        selected=legacy if legacy and legacy.get('ok') else entry.get('automatic_initial_certification',{})
        if not selected.get('ok'):
            excluded.append(dict(**entry,exclusion='program initial certification failed; needs separate planning study'));continue
        cases.append(dict(id=entry['id'],source=entry['source'],source_sha256=entry['source_sha256'],
            initial_spec=str(prep/'legacy_seed.json') if selected is legacy else (str(prep/f'automatic_seed_{i}.json') if (prep/f'automatic_seed_{i}.json').exists() else None),
            source_triangles=entry['audit']['triangles'],development_status='development validation; not a held-out generalization claim',
            initial_spec_origin='archived model-derived template' if selected is legacy else 'automatic geometry/scenario/preflight plan; no LLM'))
    protocol=dict(code_sha256=code_hash(),profile=PROFILE,cases=cases,excluded_inputs=excluded,
        cell_cap=12_000_000,mpi_processes=32,max_native_stages=6,stage_seconds=1800,episode_seconds=10800,
        model='deepseek-flash',requested_model_version='DeepSeek-V4.1-Flash',
        new_api_usd_per_source=.5,budget_authorization='user: per case <=$0.50; no total limit; all retries/arms in this campaign share source cap',
        historical_expenses='retained separately; this is a new authorized research campaign, not a reset of old episodes',
        arms=['llm','deterministic'],one_shot='identical initial snap and first layer trial; if initial snap fails, baseline remains failed',
        deterministic_controls={stage:[control_actions(stage,i) for i in range(4)] for stage in ('snap','layers')},
        scenario_context=dict(family='vehicle',objective='DrivAer mesh research; detailed geometry, layers and bounded wake allocation',
            boundary_environment='unbounded_single_phase',flow_direction=[1,0,0],up_direction=[0,0,1]),
        no_manual_dict_changes=True,preparation_sha256=sha256(prep/'preparation.json'))
    protocol['actor_settings']=dict(max_turns=6,query_turns=2,max_output=8192,reasoning_effort='low',review_policy='program',
        reason='bounded query and certified commitment; native quality/fidelity gates unchanged')
    if data.get('independent_validator'):
        protocol['independent_validator']=data['independent_validator']
        protocol['input_eligibility_policy']='complete native closure AND independent CGAL 5.6.2 EPICK certificate; native disagreements retained'
    if a.experience_store:
        snapshot=Path(a.experience_store).resolve();memory=read_json(snapshot)
        if {c.get('original_source_sha256',c['source_sha256']) for c in cases}&set(memory['training_source_groups']):
            raise ValueError('test inputs overlap original training source groups, including derived copies')
        protocol.update(experience_store=str(snapshot),experience_store_sha256=sha256(snapshot),
            memory_status='measured facts from disjoint original training cases; no generalized rule or trained weights')
    write_json(root/'protocol.json',protocol)
    write_json(root/'api_budget_scope.json',dict(run_roots=[str(root/'runs')],lock_directory=str(root/'api_case_locks'),
        authorization_scope='this campaign; previous experiments preserved',source_aliases={}))
    launch=[]
    for entry in cases:
        for arm in protocol['arms']:
            name=f'{entry["id"]}_{arm}';run=root/'runs'/name
            batch=root/'logs'/f'{name}.sbatch'
            batch.write_text(f'''#!/bin/bash
#SBATCH --job-name={name}
#SBATCH --partition=C64M256G
#SBATCH --cpus-per-task=32
#SBATCH --time=03:20:00
#SBATCH --output={root}/logs/{name}-%j.log
set -eu
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={code}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd {code}
exec {sys.executable} {code}/scripts/drivaer_episode.py {root} {entry['id']} {arm}
''')
            job=subprocess.check_output(['sbatch','--parsable',str(batch)],text=True).strip()
            receipt=dict(case=entry['id'],arm=arm,job=job,run=str(run))
            if arm=='llm':
                run.mkdir(parents=True)
                env=dict(os.environ,PYTHONPATH=str(code),PYTHONDONTWRITEBYTECODE='1')
                with (root/'logs'/f'{name}_advisor.log').open('w') as log:
                    adviser=subprocess.Popen([sys.executable,'-m','cfdmesh.cli','serve-advisor',str(run),
                        '--key-file',a.key_file,'--usd-limit','.5','--case-usd-limit','.5','--max-calls','40',
                        '--max-turns','6','--query-turns','2','--max-output','8192','--reasoning-effort','low','--review-policy','program','--seconds','14000'],
                        cwd=code,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
                receipt['advisor_pid']=adviser.pid
            launch.append(receipt);write_json(root/'launch.json',launch)
    print('cases',len(cases),'excluded',len(excluded),'jobs',len(launch),flush=True)
