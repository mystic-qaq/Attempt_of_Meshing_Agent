"""Keep the post-benchmark archived-proposal validation separate and auditable."""
import sys
from pathlib import Path
from cfdmesh.io import read_json, write_json
from portfolio_report import measured_attempt, select_attempt
from cfdmesh.scientific_advisor import geometry_spend

root=Path(sys.argv[1]); out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True)
protocol=read_json(root/'portfolio_protocol.json')
entry=next(e for e in protocol['cases'] if e['id']=='ahmed_public_25')
old=read_json(Path(entry['parent'])/'agent_run.json')
validation=read_json(root/'proposal_validation_result.json')
follow=read_json(root/'proposal_followup_result.json')
if follow['status']=='running':raise ValueError('follow-up is not complete')
attempts=[]
for phase,run in [('historical_development',old),('archived_model_proposal_validation',validation['result']),('separate_online_followup',follow)]:
    for r in run['rounds']:
        a=measured_attempt(r,phase,len(attempts)+1,run['code_sha256'])
        a['execution_decision_origin']=a['decision_origin']
        if phase=='archived_model_proposal_validation':a['decision_origin']='archived_model_proposal_validation'
        attempts.append(a)
if len(attempts)>5:raise ValueError('source attempt cap violated')
selected=select_attempt(attempts);base=attempts[0]
_,cost,own=geometry_spend(root/'runs/proposal_followup_ahmed_public_25')
c=dict(id='ahmed_public_25',family='vehicle',split='separate_validation_after_online_interface_failure',
       attempts=attempts,baseline=base,selected=selected,mesh_attempts=len(attempts),
       joint_accepted=follow['accepted'],source_api_usd_upper=cost,followup_api_usd_upper=own,
       handoff=read_json(root/'runs/proposal_followup_ahmed_public_25/handoff.json'))
write_json(out/'separate_results.json',dict(cases=[c],online_benchmark=False,
    note='After the primary online interface failure, execute an already-certified archived model feedback proposal unchanged, then allow remaining audited online attempts. This is separate from the frozen main experiment.',
    proposal_receipt=validation['protocol']))
lines=['# Separate vehicle proposal validation','',
    'This follow-up was added after the main online vehicle plan failed its interface. It is not merged into the frozen main comparison. The earlier certified model proposal was executed without parameter edits and without another API call. Remaining source-wide native attempts were then available to an online follow-up.', '',
    '| Attempt | Origin | Cells | Actual ≥5-layer area | Q / geometry / scene |','|---|---|---:|---:|---|']
for a in attempts:
    lines.append(f"| {a['attempt']} | {a['decision_origin']} | {a['cells']} | {100*a['layer_coverage']:.2f}% | {a['quality_accepted']} / {a['fidelity_accepted']} / {a['scene_accepted']} |")
if selected:
    gain=100*(selected['layer_coverage']-base['layer_coverage']); cell_gain=(selected['cells']/base['cells']-1)*100
    lines += ['',f"Selected admissible diagnostic candidate: attempt {selected['attempt']}, coverage {100*base['layer_coverage']:.2f}% → {100*selected['layer_coverage']:.2f}% ({gain:+.2f} percentage points), cells {int(base['cells']):,} → {int(selected['cells']):,} ({cell_gain:+.2f}%).", '',
              f"Selected joint acceptance: {selected['joint_accepted']}. Outstanding reasons: "+('; '.join(selected['reasons']) or 'none')+'.', '']
lines += [f"Same-source API peak-price upper bound, including earlier development and the failed main plan: ${cost:.6f}. Total native attempts across all related phases: {len(attempts)} (cap five).", '',
          '![Native layer comparison](../assets/model_feedback_car_layers.png)', '',
          '![Actual volume cut comparison](../assets/model_feedback_car_cuts.png)', '',
          'A wall-coverage gain is not a demonstration of correct y+, sufficient outer-layer thickness or converged RANS accuracy. The complete outstanding gates remain visible. This targeted validation does not replace a frozen held-out benchmark.', '',
          '## All failure reasons','']
for a in attempts:lines.append(f"- Attempt {a['attempt']}: "+('; '.join(a['reasons']) or 'all configured gates passed'))
(out/'RESULTS_APPENDIX.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('Separate report complete; combined native attempts:',len(attempts))
