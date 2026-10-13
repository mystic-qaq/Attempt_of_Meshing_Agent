"""Separate two-attempt online follow-up after the archived proposal validation."""
import sys
from pathlib import Path
from cfdmesh.agent import run_agent
from cfdmesh.io import read_json, write_json, code_hash

root=Path(sys.argv[1]); protocol=read_json(root/'portfolio_protocol.json')
entry=next(e for e in protocol['cases'] if e['id']=='ahmed_public_25')
parent=root/'runs/proposal_validation_ahmed_public_25'
old=read_json(Path(entry['parent'])/'agent_run.json')
online=read_json(root/'runs/ahmed_public_25/agent_run.json')
fixed=read_json(parent/'agent_run.json')
if any(r['status']=='running' for r in (old,online,fixed)):raise ValueError('parent episode active')
before=sum(len(r['rounds']) for r in (old,online,fixed))+old.get('prior_mesh_attempts',0)
remaining=5-before
if not 1<=remaining<=2:raise ValueError('external source-wide attempt audit failed')
write_json(root/'proposal_followup_protocol.json',dict(online_benchmark=False,
    purpose='online follow-up of a separately validated archived model proposal',
    source_mesh_attempts_before=before,max_new_attempts=remaining,core_sha256=code_hash(),
    cap_includes_archived_v6_online_portfolio_and_fixed_validation=True))
run=run_agent(entry['source'],root/'runs/proposal_followup_ahmed_public_25',
    Path.home()/'.conda-envs/openfoam2412',budget=2_000_000,max_rounds=remaining,n_procs=16,
    advisor='deepseek-flash',round_seconds=600,total_seconds=2000,require_layers=True,
    flow=dict(speed=30.,nu=1.5e-5,yplus=50.,layers=8),flow_probe=True,model_plan=True,
    resume_from=parent,scenario_context=read_json(entry['scenario_file']))
write_json(root/'proposal_followup_result.json',run)
print('separate proposal follow-up:',run['status'],run.get('stop_reason'))
