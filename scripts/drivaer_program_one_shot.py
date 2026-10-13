"""A genuinely programmatic geometry/scenario plan, with one full native attempt."""
import argparse
from pathlib import Path
from cfdmesh.agent import run_agent
from cfdmesh.io import read_json,code_hash

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('protocol');p.add_argument('out');a=p.parse_args()
    protocol=read_json(a.protocol);entry=protocol['cases'][0]
    result=run_agent(entry['source'],a.out,Path.home()/'.conda-envs/openfoam2412',
        budget=12_000_000,max_rounds=1,n_procs=32,round_seconds=1800,total_seconds=3600,
        require_layers=True,flow=dict(speed=30.,nu=1.5e-5,yplus=50.,layers=8),
        advisor='none',model_plan=False,centre_geometry=True,scenario_context=protocol['scenario_context'])
    print(result['status'],result.get('stop_reason'),flush=True)
