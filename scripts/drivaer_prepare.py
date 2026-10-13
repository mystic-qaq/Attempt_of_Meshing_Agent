"""Audit immutable real inputs and exercise native stage copying before paid episodes."""
import argparse
import time
from pathlib import Path
import trimesh
from cfdmesh.geometry import prepare
from cfdmesh.planning import initial_plan, certify, preflight_replan
from cfdmesh.case_builder import MeshSpec
from cfdmesh.scenario import compile_scenario, prior_actions, flow_region
from cfdmesh.runner import run_round, command, environment
from cfdmesh.agent import evaluate
from cfdmesh.stages import register_snap
from cfdmesh.verify import surface_report
from cfdmesh.io import write_json, read_json, code_hash, sha256

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--of-root',required=True)
    p.add_argument('--source',action='append',default=[]);p.add_argument('--legacy-spec')
    p.add_argument('--cgal-validator',help='optional independent exact-predicate executable; both native and CGAL reports retained')
    p.add_argument('--reuse-smoke-receipt',help='use an existing hash-bound native integration receipt; no repeated smoke mesh')
    a=p.parse_args();root=Path(a.root).resolve()
    if (root/'preparation.json').exists():raise FileExistsError('preparation is immutable')
    root.mkdir(parents=True,exist_ok=True);summary=dict(code_sha256=code_hash(),inputs=[],smoke=None)
    if a.cgal_validator:summary['independent_validator']=dict(executable=str(Path(a.cgal_validator).resolve()),executable_sha256=sha256(a.cgal_validator))
    fixture=root/'smoke';fixture.mkdir();source=fixture/'source.stl'
    trimesh.creation.box(extents=[1.,.6,.4]).export(source)
    geom=prepare(source,fixture/'input',n=256,centre_geometry=True)
    spec,physics=initial_plan(geom,2_000_000)
    smoke_certificate=None
    if a.cgal_validator:
        from cfdmesh.surface_contract import run_independent_audit
        smoke_certificate=run_independent_audit(geom.path,a.cgal_validator,fixture/'input/cgal',environment(a.of_root),time.monotonic()+300)
    if a.reuse_smoke_receipt:
        previous=read_json(a.reuse_smoke_receipt)
        if previous['code_sha256']!=code_hash():raise ValueError('smoke implementation differs')
        from cfdmesh.stages import verify_snap_unchanged
        prior_root=Path(a.reuse_smoke_receipt).parent
        verify_snap_unchanged(read_json(prior_root/'smoke/snap/snap_anchor.json'))
        summary['smoke']=dict(previous['smoke'],reused_receipt=a.reuse_smoke_receipt,reused_receipt_sha256=sha256(a.reuse_smoke_receipt))
        evidence={'accepted':False}
    else:
        native=run_round(spec,geom.path,fixture/'snap',a.of_root,n_procs=8,round_seconds=600,budget=2_000_000,stage='snap',input_surface_certificate=smoke_certificate)
        evidence=evaluate(native,geom,fixture/'snap',spec,physics,2_000_000,require_layers=False)
        summary['smoke']=dict(snap_accepted=evidence['accepted'],snap_error=native.get('error'))
    if evidence['accepted']:
        anchor=register_snap(fixture/'snap',spec,geom.path,evidence,2_000_000)
        trial=run_round(spec,geom.path,fixture/'layers',a.of_root,n_procs=8,round_seconds=600,budget=2_000_000,stage='layers',snap_anchor=anchor,input_surface_certificate=smoke_certificate)
        ev=evaluate(trial,geom,fixture/'layers',spec,physics,2_000_000,require_layers=True)
        summary['smoke'].update(layer_native_complete=bool((trial.get('quality') or {}).get('verified')),
            layer_error=trial.get('error'),source_mutated=trial.get('snap_copy',{}).get('source_mutated'),
            layer_coverage=ev['layers'].get('coverage'),
            layer_stage_steps=[s['name'] for s in trial['steps']])
    for i,path in enumerate(a.source):
        path=str(Path(path).resolve())
        item=dict(source=path,source_sha256=sha256(path),id=Path(path).stem if Path(path).stem.startswith('drivaer_') else f'drivaer_{i+1}')
        try:
            geom=prepare(path,root/f'input{i}',centre_geometry=True)
            step,text=command([Path(a.of_root)/'bin/surfaceCheck','-checkSelfIntersection','body.stl'],root/f'input{i}',environment(a.of_root),root/f'input{i}'/'nativeSurfaceCheck.log',time.monotonic()+300)
            from cfdmesh.surface_contract import run_independent_audit,composite_surface_report
            certificate=run_independent_audit(geom.path,a.cgal_validator,root/f'input{i}/cgal',environment(a.of_root),time.monotonic()+300) if a.cgal_validator else None
            item.update(native=composite_surface_report(text,step['returncode'],geom.path,certificate),audit=geom.audit)
            spec,physics=initial_plan(geom,12_000_000,flow=dict(speed=30.,nu=1.5e-5,yplus=50.,layers=8),flow_length=geom.mesh.extents[0])
            scene=compile_scenario(dict(family='vehicle',objective='DrivAer mesh research',boundary_environment='unbounded_single_phase',flow_direction=[1,0,0],up_direction=[0,0,1]),geom,physics)
            for action in prior_actions(spec,geom,scene):spec.regions.append(flow_region(spec,action,geom,scene))
            spec,trace=preflight_replan(spec,geom,12_000_000)
            item['automatic_initial_certification']=certify(spec,geom,12_000_000)
            write_json(root/f'automatic_seed_{i}.json',spec.to_dict())
            if i==0 and a.legacy_spec:
                data=read_json(a.legacy_spec);data=data.get('spec',data)
                legacy=MeshSpec.from_dict(data);legacy.quality.max_boundary_skewness=4.;legacy.quality.check_min_face_weight=.05
                item['legacy_seed_certification']=certify(legacy,geom,12_000_000)
                write_json(root/'legacy_seed.json',legacy.to_dict())
        except Exception as exc:item['error']=f'{type(exc).__name__}: {exc}'
        summary['inputs'].append(item);write_json(root/'preparation.json',summary)
    write_json(root/'preparation.json',summary)
    print('preparation complete',summary['smoke'],flush=True)
