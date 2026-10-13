"""Native validation of a pre-existing model feedback proposal; separate from online benchmark."""
import argparse
from pathlib import Path
from cfdmesh.agent import run_agent
from cfdmesh.io import read_json, write_json, sha256, code_hash

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('root'); p.add_argument('case')
    p.add_argument('replay_report'); args = p.parse_args()
    root = Path(args.root); protocol = read_json(root/'portfolio_protocol.json')
    entry = next(e for e in protocol['cases'] if e['id'] == args.case)
    parent = read_json(Path(entry['parent'])/'agent_run.json')
    replay = read_json(args.replay_report)
    if not replay['proposal_certified'] or replay['source_sha256'] != entry['source_sha256']:
        raise ValueError('pre-existing proposal not certified for this source')
    online = read_json(root/'runs'/args.case/'agent_run.json')
    if online['status'] == 'running': raise ValueError('online episode still active')
    count = len(parent['rounds'])+len(online['rounds'])+parent.get('prior_mesh_attempts', 0)
    if count+1 > 5: raise ValueError('combined source mesh attempt cap exhausted')
    out = root/'runs'/('proposal_validation_'+args.case)
    receipt = dict(purpose='separate native validation of pre-existing model feedback proposal',
        online_benchmark=False, source_sha256=entry['source_sha256'], core_sha256=code_hash(),
        replay_report_sha256=sha256(args.replay_report), proposal_source=str(args.replay_report),
        parameters_modified_after_replay=False, extra_api_calls=0,
        source_mesh_attempts_before=count, allowed_new_attempts=1,
        selection_reason='Online model returned an incomplete restore action. Validate the earlier certified model proposal unchanged; do not attribute this to online repair success.')
    write_json(root/'proposal_validation_protocol.json', receipt)
    flow=dict(speed=30.,nu=1.5e-5,yplus=50.,layers=8)
    run=run_agent(entry['source'],out,Path.home()/'.conda-envs/openfoam2412',
        budget=2_000_000,max_rounds=1,n_procs=16,advisor='none',round_seconds=600,total_seconds=1200,
        require_layers=True,flow=flow,flow_probe=True,model_plan=False,initial_override=replay['spec'],
        scenario_context=read_json(entry['scenario_file']))
    write_json(root/'proposal_validation_result.json',dict(protocol=receipt,result=run))
    print('pre-existing model proposal native validation:',run['status'],run.get('stop_reason'))
