"""Audit an immutable real-geometry episode and render actual native meshes.

Run on a compute node. Coordinates below are predeclared DrivAer diagnostic
boxes in the recorded centred frame, not source semantic-part segmentation.
"""
import argparse,copy,shutil
from pathlib import Path
import numpy as np
from cfdmesh.io import read_json,write_json,sha256
from cfdmesh.verify import obj_face_geometry
from scripts.portfolio_visualize import wall_data
from scripts.drivaer_visualize import render_case

ROIS={
 'front_lateral_lower':([-1.9,-1.1,-.8],[-1.0,1.1,-.20]),
 'rear_lateral_lower':([.85,-1.1,-.8],[1.65,1.1,-.20]),
 'central_lower':([-1.9,-.55,-.8],[1.8,.55,-.35])}

def layer_rois(case):
    v,faces,layers,coverage=wall_data(case);areas,centres=obj_face_geometry(case/'body.obj')
    result={}
    for name,(lo,hi) in ROIS.items():
        mask=np.all(centres>=lo,axis=1)&np.all(centres<=hi,axis=1)
        if 'lateral' in name:mask&=np.abs(centres[:,1])>=.6
        area=float(areas[mask].sum())
        result[name]=dict(min=lo,max=hi,abs_y_min=.6 if 'lateral' in name else None,faces=int(mask.sum()),area=area,
                         ge1=float(areas[mask&(layers>=1)].sum()/area) if area else None,
                         ge5=float(areas[mask&(layers>=5)].sum()/area) if area else None)
    return dict(coverage_ge5=coverage,regions=result,definition='native wall-face-centre selection and full polygon areas; not exact clipped areas or semantic parts')

def compact(record,run):
    e=record['evidence'];q=e.get('quality') or {};layers=e.get('layers',{});fractions=layers.get('area_fraction_by_layers',{})
    return dict(round=record['round'],attempt=record['round']+1,arm='new_agent',case=str(run/f'round{record["round"]}'),
        cells=q.get('metrics',{}).get('cells'),coverage_ge1=sum(v for k,v in fractions.items() if int(k)>=1),coverage_ge5=layers.get('coverage'),
        requested_layers=record['spec']['layers']['n_surface_layers'],coverage_requested=sum(v for k,v in fractions.items() if int(k)>=record['spec']['layers']['n_surface_layers']),
        metrics=q.get('metrics'),basic_failed_checks=q.get('n_failed'),point_fans=q.get('boundary_disconnected_point_fans'),shared_edges=q.get('body_shared_edge_defect'),
        quality_pass=q.get('accepted'),fidelity_pass=e.get('fidelity',{}).get('accepted'),scenario_pass=(e.get('scenario_screen') or {}).get('accepted'),
        joint_pass=e.get('accepted'),admissible_diagnostic=bool(q.get('accepted') and e.get('fidelity',{}).get('accepted') and (e.get('scenario_screen') or {}).get('accepted')),
        native_error=record['native'].get('error'),reasons=e.get('reasons'),actions=record['decision'].get('executed_actions'),decision_source=record['decision']['source'],
        hypothesis=(record['decision'].get('advisor') or {}).get('hypothesis'),advisor_error=(record['decision'].get('receipt') or {}).get('error'),
        tool_queries=(record['decision'].get('receipt') or {}).get('tool_queries'),scientific_review_completed=(record['decision'].get('receipt') or {}).get('scientific_review_completed'),
        estimated_yplus=layers.get('estimated_yplus'),native_seconds=record['native'].get('seconds'))

def main():
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('out');p.add_argument('--reference',required=True);p.add_argument('--old-agent-case');p.add_argument('--direct-case');a=p.parse_args()
    run=Path(a.run);out=Path(a.out);out.mkdir(parents=True,exist_ok=False);(out/'figures').mkdir();(out/'dicts').mkdir();(out/'checks').mkdir()
    current=read_json(run/'agent_run.json');old=read_json(a.reference)
    if current['status']=='running':raise ValueError('wait for immutable episode completion')
    if current['source_sha256']!=old['source_sha256']:raise ValueError('source mismatch')
    rounds=[compact(r,run) for r in current['rounds']]
    raw_checks={}
    for row in rounds:
        case=Path(row['case']);target=out/'dicts'/f'attempt{row["attempt"]}';shutil.copytree(case/'system',target)
        for name in ('checkMesh.log','checkMeshExtended.log','nativeBoundaryCheck.log'):
            raw=case/'logs'/name
            if raw.exists():
                key=f'attempt{row["attempt"]}_{name}';raw_checks[key]=sha256(raw)
                data=raw.read_text(errors='replace').replace(str(run),'<NEW_RUN>').replace(str(Path.home()),'<HOME>')
                (out/'checks'/key).write_text(data)
        row['local_layers']=layer_rois(case) if (case/'body.obj').exists() and (case/'0/nSurfaceLayers').exists() else None
    valid=[r for r in rounds if r['admissible_diagnostic']]
    best=max(valid,key=lambda r:r['coverage_ge5'] or 0) if valid else None
    # A separate maximum is shown as rejected diagnostic, never chosen for handoff.
    highest=max(rounds,key=lambda r:r['coverage_ge5'] or 0) if rounds else None
    renders=[]
    for row in ([rounds[0]] if rounds else [])+([highest] if highest and highest['round']!=0 else []):
        renders.append(render_case(row,out/'figures'))
    anchors=[]
    for arm,path in (('agent',a.old_agent_case),('expert',a.direct_case)):
        if path:
            row=max([r for r in old['attempts'] if r['arm']==arm],key=lambda r:r['coverage_ge5'])
            anchors.append(dict(arm=arm,attempt=row['attempt'],local_layers=layer_rois(Path(path))))
    result=dict(status=current['status'],stop_reason=current.get('stop_reason'),source_sha256=current['source_sha256'],code_sha256=current['code_sha256'],
                version_episode='new <=5-attempt episode; prior benchmark unchanged',attempts=rounds,best_admissible_round=best['round'] if best else None,
                highest_rejected_diagnostic_round=highest['round'] if highest else None,old_reference=old['attempts'],local_anchor_comparison=anchors,
                native_render_manifest=renders,raw_check_log_sha256=raw_checks,limitations=['not independent held-out geometry','different actual cell counts','regional boxes selected before new results','no actual CFD y+ or force validation','Fluent external report not comparable'])
    # Private physical paths do not belong to the publication package.
    def portable(x):
        if isinstance(x,dict):return {k:portable(v) for k,v in x.items()}
        if isinstance(x,list):return [portable(v) for v in x]
        if isinstance(x,str):return x.replace(str(run),'<NEW_RUN>').replace(str(Path.home()),'<HOME>')
        return x
    write_json(out/'comparison.json',portable(result))
    write_json(out/'protocol.json',portable(read_json(run/'EPISODE_PROTOCOL.json')))
    if (run/'ADVISOR_CONFIG_CHANGE.json').exists():
        write_json(out/'advisor_config_change.json',{k:v for k,v in read_json(run/'ADVISOR_CONFIG_CHANGE.json').items() if k!='new_pid'})
    if (run/'advisor/usage.json').exists():write_json(out/'usage.json',read_json(run/'advisor/usage.json'))
    print([(r['attempt'],r['cells'],r['coverage_ge5'],r['basic_failed_checks']) for r in rounds],flush=True)

if __name__=='__main__':main()
