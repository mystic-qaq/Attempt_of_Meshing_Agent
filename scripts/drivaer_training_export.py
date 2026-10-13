"""Visible state/action/outcome records for future SFT and student-rollout OPD.

This exporter does not train a student and never exports private reasoning_content.
"""
import argparse
import json
from pathlib import Path
from cfdmesh.io import read_json,write_json

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('experiment');p.add_argument('output');a=p.parse_args()
    root=Path(a.experiment);out=Path(a.output)
    if out.exists():raise FileExistsError('training export must be fresh')
    out.mkdir(parents=True);records=[]
    for run in sorted((root/'runs').iterdir()):
        if not (run/'agent_run.json').exists():continue
        data=read_json(run/'agent_run.json')
        for row in data['rounds']:
            decision=row['decision']
            if decision['source']!='model':continue
            previous=row['round']-1;request=run/'advisor'/f'request_{previous}.json'
            if not request.exists():continue
            receipts=[dict(tool=read_json(q)['name'],arguments=read_json(q)['arguments'],
                observation=read_json(q.with_name(q.name.replace('tool_request_','tool_response_'))))
                for q in sorted((run/'advisor').glob(f'tool_request_{previous}_*.json'))
                if q.with_name(q.name.replace('tool_request_','tool_response_')).exists()]
            records.append(dict(case=run.name,source_sha256=data['source_sha256'],code_sha256=data['code_sha256'],
                visible_state=read_json(request)['evidence'],tool_receipts=receipts,
                teacher_action=decision.get('advisor'),executed_actions=decision.get('executed_actions'),
                outcome=dict(stage=row['stage'],research_eligible=row['research_eligible'],
                    quality=row['evidence']['quality'],fidelity_accepted=row['evidence']['fidelity']['accepted'],
                    layer_coverage=row['evidence']['layers'].get('coverage'),regional_layers=row['regional_layers'],
                    reasons=row['evidence']['reasons']),
                use='visible trajectory with measured outcome; not automatically a positive imitation target'))
    with (out/'trajectories.jsonl').open('w',encoding='utf-8') as f:
        for record in records:
            text=json.dumps(record,ensure_ascii=False,allow_nan=False)
            if 'reasoning_content' in text:raise ValueError('private reasoning must not enter training export')
            f.write(text+'\n')
    write_json(out/'manifest.json',dict(records=len(records),hidden_reasoning_exported=False,
        status='trajectory preparation only; no student training or OPD result',
        student_rollout_required_for_opd=True,source_mutated=False))
    print('visible measured teacher trajectories',len(records))
