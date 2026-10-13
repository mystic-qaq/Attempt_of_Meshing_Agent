"""Freeze paired parameters from a completed DrivAer preparation; launch nothing."""
import argparse
from pathlib import Path
from cfdmesh.budget_scope import sync_budget_scope
from cfdmesh.drivaer import PROFILE
from cfdmesh.io import code_hash, read_json, sha256, write_json


def freeze(preparation, experiment, *, mode='full', stages=4, processes=32, history=None):
    preparation=Path(preparation).resolve();experiment=Path(experiment).resolve()
    data=read_json(preparation/'preparation.json');smoke=data['smoke']
    if mode not in ('full','staged') or not 1 <= stages <= 6 or processes < 1:
        raise ValueError('invalid execution allocation')
    if data['code_sha256'] != code_hash():
        raise ValueError('preparation implementation changed')
    if not smoke.get('snap_accepted') or not smoke.get('layer_native_complete') or smoke.get('source_mutated') is not False:
        raise ValueError('native stage integration has not passed')
    if experiment.exists():
        raise FileExistsError('experiment output must be fresh')
    cases=[];excluded=[]
    for index,item in enumerate(data['inputs']):
        if item.get('error') or not item.get('native',{}).get('accepted') or not item.get('automatic_initial_certification',{}).get('ok'):
            excluded.append(item);continue
        source=Path(item['source']).resolve();seed=preparation/f'automatic_seed_{index}.json'
        if sha256(source) != item['source_sha256'] or not seed.is_file():
            raise ValueError('preparation source or seed changed')
        cases.append(dict(id=item['id'],source=str(source),source_sha256=item['source_sha256'],
            initial_spec=str(seed),initial_spec_sha256=sha256(seed),initial_spec_origin='automatic geometry/scenario/preflight plan'))
    if not cases:
        raise ValueError('no eligible prepared inputs')
    protocol=dict(code_sha256=code_hash(),profile=PROFILE,cases=cases,excluded_inputs=excluded,
        cell_cap=12_000_000,mpi_processes=processes,max_native_stages=stages,
        stage_seconds=1800,episode_seconds=10800,native_mode=mode,actor_model='deepseek-flash',
        arms=['llm','deterministic'],new_api_usd_per_source=.5,
        scenario_context=dict(family='vehicle',objective='DrivAer mesh research',
            boundary_environment='unbounded_single_phase',flow_direction=[1,0,0],up_direction=[0,0,1]),
        preparation_sha256=sha256(preparation/'preparation.json'),
        initialization='identical automatic seed; first execution is programmatic in both arms',
        accounting='same-source retries and related experiment roots share the API ceiling')
    if data.get('independent_validator'):
        validator=data['independent_validator']
        if sha256(validator['executable']) != validator['executable_sha256']:
            raise ValueError('prepared validator changed')
        protocol['independent_validator']=validator
    if history and not (Path(history)/'api_budget_scope.json').is_file():
        raise ValueError('history requires a valid shared budget scope')
    experiment.mkdir();(experiment/'runs').mkdir()
    write_json(experiment/'protocol.json',protocol)
    sync_budget_scope(experiment,history)
    return protocol


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preparation');parser.add_argument('experiment')
    parser.add_argument('--mode',choices=['full','staged'],default='full')
    parser.add_argument('--stages',type=int,default=4)
    parser.add_argument('--processes',type=int,default=32)
    parser.add_argument('--history',help='previous experiment in the same authorized budget scope')
    args=parser.parse_args()
    result=freeze(args.preparation,args.experiment,mode=args.mode,stages=args.stages,processes=args.processes,history=args.history)
    print('Frozen cases:',len(result['cases']),'excluded:',len(result['excluded_inputs']),'no jobs launched')
