"""Bounded DrivAer research episodes, with independent snap and layer trials."""
import copy
import json
import re
import time
from pathlib import Path
import numpy as np
from .agent import evaluate
from .case_builder import MeshSpec
from .geometry import prepare
from .io import code_hash, read_json, write_json, sha256
from .planning import (initial_plan, preflight_replan, apply_actions, normalise_actions,
                       deterministic_actions, certify, LAYER_PARAMETERS, SNAP_PARAMETERS,
                       RESOLUTION_PARAMETERS, GENERATION_QUALITY_PARAMETERS)
from .runner import run_round, command, environment
from .scenario import compile_scenario, prior_actions, flow_region, evidence_ids
from .scientific_tools import scales
from .scientific_advisor import request_advice
from .candidates import catalog, compact_catalog, plan_signature
from .stages import register_snap, snap_signature
from .verify import surface_report, boundary_scalar, obj_face_geometry
from .layer_design import measure_layer_design


PROFILE = dict(name='DrivAer meshing research', model='deepseek-flash',
    model_weights='https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash',
    geometry_policy='all source triangles preserved; reversible bbox-centre translation',
    environment='unbounded single-phase; flow +X, up +Z; no road/rotating-wheel claim',
    first_height_policy='fixed physical flat-plate estimate; identical between arms',
    improvement_threshold_pp=10., maximum_cell_growth=1.20,
    production_accuracy='unverified; no converged CFD in this research episode')


def add_observer_target(evidence,native,spec,geom):
    """Expose the exact rejected polygon location without asserting a physical intersection."""
    text=native.get('error') or ''
    match=re.search(r'boundary face (\d+) bbox (\[[^\]]+\]) \.\. (\[[^\]]+\])',text)
    if not match:return
    lo=np.array(json.loads(match[2]),float);hi=np.array(json.loads(match[3]),float)
    if lo.shape!=(3,) or hi.shape!=(3,) or not np.isfinite([lo,hi]).all():return
    margin=2*scales(spec,geom)['global_surface_cell_metres']
    target=dict(id='boundary_observer:0',cause='boundary_observation',metric='boundary_observer',count=1,
        min=(lo-margin).tolist(),max=(hi+margin).tolist(),centroid=((lo+hi)/2).tolist(),
        native_face=int(match[1]),exact_polygon_bbox={'min':lo.tolist(),'max':hi.tolist()},
        cause_status='location of observer rejection; not proof of a physical self-intersection',
        source_error=text)
    evidence['spatial']=[d for d in evidence.get('spatial',[]) if d['id']!=target['id']]+[target]


def research_eligible(evidence, native, budget):
    q = evidence.get('quality') or {}; f = evidence.get('fidelity') or {}
    scene = evidence.get('scenario_screen')
    cells = q.get('metrics', {}).get('cells')
    return bool(q.get('verified') and q.get('accepted') and f.get('accepted')
                and not native.get('error') and cells is not None and 0 < cells <= budget
                and (scene is None or scene.get('accepted')))


def regional_layers(case, geom):
    """Frozen bbox-relative diagnostic regions, not semantic part labels."""
    fields = [p for p in Path(case).glob('*/nSurfaceLayers') if p.parent.name.replace('.', '', 1).isdigit()]
    if not fields:
        return dict(available=False, reason='native layer field unavailable')
    try:
        values, uniform = boundary_scalar(max(fields, key=lambda p: float(p.parent.name)))
        areas, centres = obj_face_geometry(Path(case) / 'body.obj')
        if uniform: values = np.full(len(areas), values[0])
        if len(values) != len(areas) or not len(areas): raise ValueError('wall-field alignment unavailable')
        lo, hi = geom.mesh.bounds; unit = (centres - lo) / (hi - lo)
        lateral = np.abs(unit[:, 1] - .5) >= .30
        boxes = {
            'front_lower_lateral': (unit[:, 0] >= .10) & (unit[:, 0] <= .35) & (unit[:, 2] <= .40) & lateral,
            'rear_lower_lateral': (unit[:, 0] >= .65) & (unit[:, 0] <= .90) & (unit[:, 2] <= .40) & lateral,
            'central_lower': (unit[:, 0] >= .35) & (unit[:, 0] <= .65) & (unit[:, 2] <= .35),
        }
        regions = {}
        for name, mask in boxes.items():
            area = float(areas[mask].sum())
            regions[name] = dict(area=area, faces=int(mask.sum()),
                coverage_ge1=float(areas[mask & (values >= 1)].sum()/area) if area else None,
                coverage_ge5=float(areas[mask & (values >= 5)].sum()/area) if area else None)
        return dict(available=True, regions=regions, definition='complete wall polygons selected by face centre; bbox-relative boxes fixed before trials; no exact part segmentation')
    except Exception as exc:
        return dict(available=False, reason=str(exc))


def dominates(a, b):
    """Keep a feasible coverage/cell Pareto archive; invalid meshes never win."""
    values=[(a['coverage'],b['coverage']),(-a['cells'],-b['cells'])]
    da=a.get('layer_design');db=b.get('layer_design')
    if da and db and da.get('available') and db.get('available'):
        values.extend([(da['coverage_original_target'],db['coverage_original_target']),
                       (-da['area_below_half_original_stack'],-db['area_below_half_original_stack'])])
        pa=da.get('coverage_design_proxy');pb=db.get('coverage_design_proxy')
        if (pa is None)!=(pb is None):return False
        if pa is not None:values.append((pa,pb))
    return all(x>=y for x,y in values) and any(x>y for x,y in values)


def update_archive(archive, record):
    if not record['research_eligible'] or record['stage'] not in ('layers','full'): return archive
    item = dict(round=record['round'], case=record['native']['case'], spec=record['spec'],
                coverage=record['evidence']['layers'].get('coverage') or 0.,
                coverage_ge1=1-record['evidence']['layers'].get('area_fraction_by_layers',{}).get('0',1.),
                cells=record['evidence']['quality']['metrics']['cells'],
                regional_layers=record['regional_layers'],layer_design=record.get('layer_design'))
    if any(dominates(old, item) for old in archive): return archive
    return [old for old in archive if not dominates(item, old)] + [item]


def control_actions(stage, step,calibrated=False):
    """Frozen stock-parameter control, stronger than simply repeating a one-shot mesh."""
    if stage=='full':
        if calibrated:
            choices=[
                [dict(kind='surface_refine')],
                [dict(kind='surface_refine'),dict(kind='snap_settings',parameters=dict(n_smooth_patch=5,n_solve_iter=70,n_relax_iter=10,n_face_split_interval=10,avoid_diagonal=True)),dict(kind='layer_settings',parameters=dict(merge_patch_faces_angle=30,n_outer_iter=1))],
                [dict(kind='surface_refine'),dict(kind='snap_settings',parameters=dict(n_smooth_patch=6,n_solve_iter=70,n_relax_iter=10,n_feature_snap_iter=20,avoid_diagonal=True,explicit_feature_snap=False,implicit_feature_snap=True)),dict(kind='layer_settings',parameters=dict(n_surface_layers=8,expansion_ratio=1.10,n_outer_iter=1,merge_patch_faces_angle=30))]]
            return [{**a,'why':'frozen generic higher-resolution full control under measured cost planning; original first height and native acceptance unchanged',
                'evidence':['geometry','quality','layers']} for a in choices[min(step,len(choices)-1)]]
        choices=[
            [dict(kind='snap_settings',parameters=dict(n_smooth_patch=5,n_solve_iter=70,n_relax_iter=10,n_feature_snap_iter=20,n_face_split_interval=10,avoid_diagonal=True)),dict(kind='layer_settings',parameters=dict(merge_patch_faces_angle=30,n_outer_iter=1))],
            [dict(kind='layer_settings',parameters=dict(n_surface_layers=8,expansion_ratio=1.10,n_outer_iter=1,n_grow=0,merge_patch_faces_angle=30))],
            [dict(kind='layer_settings',parameters=dict(mesh_shrinker='displacementMotionSolver',n_surface_layers=8,expansion_ratio=1.10,n_outer_iter=1,merge_patch_faces_angle=30))],
            [dict(kind='layer_settings',parameters=dict(mesh_shrinker='displacementMotionSolver',n_surface_layers=8,expansion_ratio=1.05,n_outer_iter=1,merge_patch_faces_angle=20,feature_angle=130))]]
        return [{**a,'why':'frozen full-pipeline control recipe; fixed original first height and eight-layer comparison',
                 'evidence':['quality','layers']} for a in choices[min(step,len(choices)-1)]]
    if stage=='snap':
        choices=[
            dict(kind='snap_settings',parameters=dict(n_smooth_patch=5,n_solve_iter=70,n_relax_iter=10,
                n_feature_snap_iter=20,n_face_split_interval=10,avoid_diagonal=True)),
            dict(kind='generation_quality',parameters=dict(min_tet_quality=1e-12,min_triangle_twist=.01)),
            dict(kind='surface_refine')]
        action=choices[min(step,len(choices)-1)]
    else:
        choices=[
            dict(n_surface_layers=6,expansion_ratio=1.15,n_outer_iter=1,n_grow=0),
            dict(mesh_shrinker='displacementMotionSolver',n_surface_layers=6,expansion_ratio=1.15,n_outer_iter=1),
            dict(mesh_shrinker='displacementMedialAxis',n_surface_layers=5,expansion_ratio=1.08,
                 n_outer_iter=1,n_smooth_thickness=20,n_smooth_surface_normals=4,n_smooth_normals=6),
            dict(mesh_shrinker='displacementMotionSolver',n_surface_layers=5,expansion_ratio=1.08,
                 n_outer_iter=1,n_smooth_thickness=20,n_smooth_surface_normals=4)]
        action=dict(kind='layer_settings',parameters=choices[min(step,len(choices)-1)])
    return [{**action,'why':'frozen DrivAer control recipe; independent of model and case outcome',
             'evidence':['quality' if stage=='snap' else 'layers']}]


def clear_gain(selected, baseline):
    if not selected or not baseline or not baseline['research_eligible']:return False
    if selected['coverage']-baseline['coverage']<PROFILE['improvement_threshold_pp']/100:return False
    if selected['cells']>baseline['cells']*PROFILE['maximum_cell_growth']:return False
    if selected['coverage_ge1']<baseline['coverage_ge1']-.02:return False
    design_before=baseline.get('layer_design');design_after=selected.get('layer_design')
    if design_before and design_before.get('available'):
        if not design_after or not design_after.get('available'):return False
        if design_after['coverage_original_target']<design_before['coverage_original_target']-.02:return False
        if design_after['area_below_half_original_stack']>design_before['area_below_half_original_stack']+.02:return False
        if design_before.get('coverage_design_proxy') is not None:
            if design_after.get('coverage_design_proxy') is None or design_after['coverage_design_proxy']<design_before['coverage_design_proxy']-.02:return False
    before=baseline['regional_layers'];after=selected['regional_layers']
    if not before.get('available') or not after.get('available'):return False
    return all(v['coverage_ge5'] is not None and after['regions'][k]['coverage_ge5'] is not None
               and after['regions'][k]['coverage_ge5']>=v['coverage_ge5']-.02
               for k,v in before['regions'].items())


def decision_evidence(record, baseline, records, geom, spec, physics, budget, scenario, archive):
    evidence = copy.deepcopy(record['evidence'])
    evidence['fidelity'].pop('bad_surface_points', None)
    evidence['layers'].pop('bad_layer_points', None)
    evidence.update(task_profile=PROFILE, stage=record['stage']+' feedback; no production accuracy claim',
        current_spec=spec.to_dict(), last_tested_spec=record['spec'],
        last_trial_research_eligible=record['research_eligible'], regional_layers=record['regional_layers'],layer_design=record.get('layer_design'),
        geometry=geom.audit, flow=physics, budget=budget, physical_scales=scales(spec,geom),
        scenario=scenario, candidate_catalog=compact_catalog(catalog(records,budget)),
        parameter_schema=dict(layer_settings=LAYER_PARAMETERS,snap_settings=SNAP_PARAMETERS,
                              resolution_settings=RESOLUTION_PARAMETERS,generation_quality=GENERATION_QUALITY_PARAMETERS),
        baseline=baseline, pareto_archive=archive,
        history=[dict(round=r['round'],stage=r['stage'],decision_source=r['decision']['source'],
            executed_actions=r['decision'].get('executed_actions'),
            native_failed_checks=(r['evidence'].get('quality') or {}).get('n_failed'),
            layer_coverage=r['evidence']['layers'].get('coverage'),regional_layers=r['regional_layers'],
            research_eligible=r['research_eligible'],reasons=r['evidence']['reasons']) for r in records],
        instructions=('Focus on this DrivAer geometry. Select one primary mechanism and at most two parameter groups. '
            'A snap-stage failure precedes all layers: repair snap/refinement, not layer smoothing. '
            'For failed layer trials the CURRENT spec is a protected anchor, not necessarily the last failed spec. '
            'Do not repeat a failed joint intervention. Query actual local evidence, then preview a small change. '
            'The research objective is valid quality/fidelity/scene plus better measured coverage at limited cell growth; '
            '90% layer coverage is still the separate production-layer gate, not a prerequisite for research improvement. '
            'Zero basic Failed checks does NOT mean accepted quality: disconnected point fans/shared edges still fail. '
            'Preserve first physical height. More cells do not enlarge extrusion space. '
            'Prefer actual improvements in the difficult local regions; global coverage alone is insufficient.'))
    return evidence


def run_drivaer(source, run_dir, of_root, arm='llm', budget=12_000_000,
                 max_stages=6, n_procs=32, round_seconds=1800, total_seconds=10800,
                 initial_spec=None, scenario_context=None, cached_failure=None,experience_store=None,
                 original_source_sha256=None,geometry_route='original triangles',cgal_validator=None,native_mode='staged',
                 actor_model='deepseek-flash',stage_comparison=None,resource_baseline=None,decision_checkpoint=None):
    if arm not in ('llm','deterministic'): raise ValueError('unknown research arm')
    if native_mode not in ('staged','full'):raise ValueError('unknown native mode')
    from .scientific_advisor import MODELS
    if actor_model!='deepseek-flash':raise ValueError('DrivAer study actor is fixed to deepseek-flash')
    profile=dict(PROFILE,model=actor_model,model_weights=MODELS[actor_model]['weights'])
    root = Path(run_dir)
    if (root/'agent_run.json').exists() or (root/'input').exists(): raise FileExistsError('fresh episode required')
    root.mkdir(parents=True,exist_ok=True); start=time.monotonic(); source_before=sha256(source)
    run=dict(status='running',accepted=False,profile=profile,arm=arm,source_sha256=source_before,
             code_sha256=code_hash(),rounds=[],pareto_archive=[],baseline=None,snap_anchors=[],
             config=dict(budget=budget,max_stages=max_stages,n_procs=n_procs,round_seconds=round_seconds,total_seconds=total_seconds,native_mode=native_mode))
    def persist():
        run['seconds']=time.monotonic()-start;run['source_mutated']=sha256(source)!=source_before
        write_json(root/'agent_run.json',run)
        write_json(root/'manifest.json',dict(purpose='paired DrivAer stage research',source_sha256=source_before,
            code_sha256=run['code_sha256'],status=run['status'],source_mutated=run['source_mutated']))
    persist()
    source_group=original_source_sha256 or source_before
    memory_sha=sha256(experience_store) if experience_store else None;resource_calibration=None
    def attach_experience(evidence,stage):
        evidence['task_profile']=profile
        if resource_calibration:
            evidence['resource_calibration']=resource_calibration
        if stage_comparison:
            from .stage_evidence import load_stage_comparison
            for name in ('snap_record','full_record'):
                if sha256(stage_comparison[name])!=stage_comparison[name+'_sha256']:
                    raise ValueError('frozen stage comparison changed')
            evidence['baseline_stage_comparison']=load_stage_comparison(stage_comparison['snap_record'],
                stage_comparison['full_record'],source_before,sha256(geom.path))
            import hashlib
            evidence['baseline_stage_comparison']['current_snap_controls_match']=hashlib.sha256(snap_signature(spec).encode()).hexdigest()==evidence['baseline_stage_comparison']['snap_signature_sha256']
        if not experience_store:return
        if sha256(experience_store)!=memory_sha:raise ValueError('frozen experience snapshot changed during evaluation')
        from .cross_case import retrieve
        snapshot=read_json(experience_store)
        evidence['cross_case_experience']=dict(snapshot_sha256=memory_sha,
            facts=retrieve(snapshot['facts'],geom.audit,physics,source_group,stage,geometry_route,allowed_training_groups=set(snapshot['training_source_groups'])),
            interpretation='measured observations from distinct original sources; remeasure current targets; no generalized positive rule yet')
        run['experience_snapshot_sha256']=memory_sha
    try:
        geom=prepare(source,root/'input',centre_geometry=True)
        step,text=command([Path(of_root)/'bin/surfaceCheck','-checkSelfIntersection','body.stl'],
            root/'input',environment(of_root),root/'input/nativeSurfaceCheck.log',min(start+total_seconds,time.monotonic()+300))
        certificate=None
        if cgal_validator:
            from .surface_contract import run_independent_audit
            certificate=run_independent_audit(geom.path,cgal_validator,root/'input/cgal',environment(of_root),min(start+total_seconds,time.monotonic()+300))
        from .surface_contract import composite_surface_report
        ingress=composite_surface_report(text,step['returncode'],geom.path,certificate);write_json(root/'input_contract.json',ingress)
        if not ingress['accepted']: raise ValueError('native source eligibility rejected')
        geom.audit['source_surface_eligibility']=dict(accepted=True,policy=ingress.get('eligibility_policy','native source checks'),
            independent_cgal=bool(certificate),native_disagreement=ingress.get('disagreement',False))
        geom.audit['self_intersection']='independent CGAL certificate verified' if certificate else 'native source check affirmative'
        write_json(root/'input/audit.json',geom.audit)
        spec,physics=initial_plan(geom,budget,flow=dict(speed=30.,nu=1.5e-5,yplus=50.,layers=8),flow_length=geom.mesh.extents[0])
        scenario=compile_scenario(scenario_context,geom,physics) if scenario_context else None
        if initial_spec: spec=MeshSpec.from_dict(initial_spec)
        else:
            if scenario:
                for action in prior_actions(spec,geom,scenario): spec.regions.append(flow_region(spec,action,geom,scenario))
            spec,preflight=preflight_replan(spec,geom,budget);write_json(root/'preflight.json',preflight)
        if not certify(spec,geom,budget)['ok']:raise ValueError('initial plan not certified')
        run['flow']=physics;run['scenario']=scenario;run['geometry_audit']=geom.audit
        if resource_baseline:
            if sha256(resource_baseline['record'])!=resource_baseline['record_sha256']:
                raise ValueError('frozen resource baseline changed')
            from .resource_model import fit_full_baseline
            resource_calibration=fit_full_baseline(resource_baseline['record'],geom,source_before)
            run['resource_calibration']=resource_calibration
        write_json(root/'initial_spec.json',spec.to_dict());write_json(root/'scenario_contract.json',scenario)
        initial=spec.to_dict()
        anchors=[];archive=[];seen=set();baseline=None;control_steps={'snap':0,'layers':0,'full':0};decision=dict(source='program_initial_plan')
        if cached_failure:
            from .stages import mesh_hashes
            old=read_json(cached_failure);old_case=Path(old['native']['case'])
            parent=read_json(Path(cached_failure).parents[1]/'agent_run.json')
            if parent['source_sha256']!=source_before or parent.get('source_mutated'):
                raise ValueError('cached failure source mismatch')
            expected='full' if native_mode=='full' else 'snap'
            if old['stage']!=expected or old['research_eligible']:
                raise ValueError('warm diagnosis expects a rejected '+expected+' experiment')
            if sha256(old_case/'constant/triSurface/body.stl')!=sha256(geom.path):
                raise ValueError('cached failure coordinate frame mismatch')
            hashes=mesh_hashes(old_case)
            add_observer_target(old['evidence'],old['native'],MeshSpec.from_dict(old['spec']),geom)
            run['warm_start']=dict(record_sha256=sha256(cached_failure),parent_code_sha256=parent['code_sha256'],
                case=str(old_case),poly_mesh_sha256=hashes,prior_native_stages=len(parent['rounds'])+parent.get('warm_start',{}).get('prior_native_stages',0),
                prior_native_seconds=sum(r['native']['seconds'] for r in parent['rounds'])+parent.get('warm_start',{}).get('prior_native_seconds',0))
            baseline=parent.get('baseline')
            if native_mode=='full' and baseline is None:
                layer=old['evidence']['layers']
                baseline=dict(round=old['round'],stage='full',cells=(old['evidence'].get('quality') or {}).get('metrics',{}).get('cells'),
                    coverage=layer.get('coverage'),coverage_ge1=1-layer.get('area_fraction_by_layers',{}).get('0',1.),
                    research_eligible=old['research_eligible'],regional_layers=old['regional_layers'],layer_design=old.get('layer_design'))
            run['baseline']=baseline
            seen.update((r['stage'],plan_signature(r['spec']) if r['stage']=='full' else snap_signature(r['spec'])) for r in parent['rounds'] if r['stage'] in ('snap','full'))
            concise=decision_evidence(old,baseline,parent['rounds'],geom,spec,physics,budget,scenario,archive)
            attach_experience(concise,expected)
            from .render import spatial_image
            spatial_image(geom,old['evidence']['spatial'],root/'input/geometry.png',scenario=scenario)
            context=dict(geometry=geom,spec=spec,evidence=old['evidence'],case=old_case,budget=budget,
                physics=physics,plan_history=parent['rounds'],scenario=scenario,mesh_stage=expected,
                native_stage_signatures=seen,snap_anchor_signatures=[],resource_calibration=resource_calibration)
            if arm=='llm':
                if decision_checkpoint:
                    from .decision_checkpoint import visible_queries
                    concise['resume_visible_queries']=visible_queries(decision_checkpoint,source_before,spec,sha256(geom.path))
                    run['decision_checkpoint']=dict(root=str(decision_checkpoint),agent_run_sha256=sha256(Path(decision_checkpoint)/'agent_run.json'))
                proposal,receipt=request_advice(root,-1,concise,timeout=1000,tool_context=context)
            else:
                proposal=dict(actions=control_actions(expected,control_steps[expected],calibrated=bool(resource_calibration)));control_steps[expected]+=1;receipt=None
            if mesh_hashes(old_case)!=hashes:raise ValueError('cached evidence mutated')
            if proposal and proposal.get('disposition')=='stop':
                run.update(status='failed',selected=None,production_accepted=False,
                    stop_reason='model stopped: '+proposal['hypothesis'],stopped_decision=proposal,stop_receipt=receipt)
                persist();return run
            if not proposal or not proposal.get('actions'):raise ValueError('no committed warm-start repair: '+str((receipt or {}).get('error')))
            spec=apply_actions(spec,proposal['actions'],geom,budget,physics_reference=physics,plan_history=parent['rounds'],scenario=scenario,spatial_evidence=old['evidence']['spatial'],resource_calibration=resource_calibration)
            decision=dict(source='model' if arm=='llm' else 'deterministic_feedback',advisor=proposal if arm=='llm' else None,receipt=receipt,executed_actions=proposal['actions'],warm_start=True)
            persist()
        for index in range(max_stages):
            if time.monotonic()-start>=total_seconds:run['stop_reason']='time budget exhausted';break
            anchor=next((a for a in reversed(anchors) if a['snap_signature']==snap_signature(spec)),None)
            stage='full' if native_mode=='full' else ('layers' if anchor else 'snap')
            signature=(stage,plan_signature(spec) if stage in ('layers','full') else snap_signature(spec))
            if signature in seen:run['stop_reason']='duplicate native stage blocked';break
            seen.add(signature);case=root/f'round{index}'
            native=run_round(spec,geom.path,case,of_root,n_procs,round_seconds,budget,start+total_seconds,
                             stage=stage,snap_anchor=anchor,input_surface_certificate=certificate)
            evidence=evaluate(native,geom,case,spec,physics,budget,require_layers=stage in ('layers','full'),scenario=scenario)
            add_observer_target(evidence,native,spec,geom)
            eligible=research_eligible(evidence,native,budget)
            record=dict(round=index,stage=stage,spec=spec.to_dict(),decision=decision,native=native,evidence=evidence,
                        accepted=evidence['accepted'],research_eligible=eligible,regional_layers=regional_layers(case,geom) if stage in ('layers','full') else dict(available=False,reason='snap has no layers'),
                        layer_design=measure_layer_design(case,spec,physics))
            run['rounds'].append(record);write_json(case/'record.json',record)
            if index==0 and stage=='snap' and not eligible and not cached_failure:
                baseline=dict(round=index,stage='snap',cells=(evidence.get('quality') or {}).get('metrics',{}).get('cells'),
                    coverage=None,research_eligible=False,regional_layers=record['regional_layers'],
                    reason='program initial snap failed; subsequent repairs are not a one-shot baseline')
                run['baseline']=baseline
            if stage=='snap' and eligible:
                saved=register_snap(case,spec,geom.path,evidence,budget);saved['spec']=spec.to_dict()
                # Receipt is the complete immutable anchor record, including its plan.
                write_json(case/'snap_anchor.json',saved);anchors.append(saved)
                run['snap_anchors']=anchors;persist();decision=dict(source='program_initial_layers' if baseline is None else 'accepted_snap_then_layers');continue
            if stage in ('layers','full') and baseline is None:
                baseline=dict(round=index,cells=(evidence.get('quality') or {}).get('metrics',{}).get('cells'),
                    coverage=evidence['layers'].get('coverage'),
                    coverage_ge1=1-evidence['layers'].get('area_fraction_by_layers',{}).get('0',1.),
                    research_eligible=eligible,regional_layers=record['regional_layers'])
                baseline['layer_design']=record['layer_design']
                run['baseline']=baseline
            archive=update_archive(archive,record);run['pareto_archive']=archive;persist()
            if index==max_stages-1:break
            if not (evidence.get('quality') or {}).get('verified'):run['stop_reason']='no completed quality evidence';break
            # Every trial starts from a measured feasible full candidate, or a safe snap.
            base=max(archive,key=lambda a:(a['coverage'],-a['cells']))['spec'] if archive else (anchors[-1]['spec'] if anchors else initial)
            spec=MeshSpec.from_dict(base)
            concise=decision_evidence(record,baseline,run['rounds'],geom,spec,physics,budget,scenario,archive)
            attach_experience(concise,stage)
            proposal=None;receipt=None
            if arm=='llm':
                from .render import spatial_image
                try:spatial_image(geom,evidence['spatial'],case/'spatial.png',scenario=scenario)
                except Exception as exc:write_json(case/'render_error.json',dict(error=str(exc)))
                proposal,receipt=request_advice(root,index,concise,timeout=min(1000,max(1,total_seconds-(time.monotonic()-start))),
                    tool_context=dict(geometry=geom,spec=spec,evidence=evidence,case=case,budget=budget,physics=physics,plan_history=run['rounds'],scenario=scenario,
                        mesh_stage=stage,native_stage_signatures=seen,snap_anchor_signatures=[a['snap_signature'] for a in anchors],resource_calibration=resource_calibration))
            if proposal and proposal.get('disposition')=='stop':
                run['stop_reason']='model stopped: '+proposal['hypothesis'];run['stopped_decision']=proposal;run['stop_receipt']=receipt;break
            actions=(proposal or {}).get('actions')
            decision=dict(source='model' if actions else 'deterministic_feedback',advisor=proposal,receipt=receipt)
            if not actions:
                actions=control_actions(stage,control_steps[stage],calibrated=bool(resource_calibration));control_steps[stage]+=1
            try:
                valid={'geometry','quality','fidelity','layers','physics'}|{d['id'] for d in evidence['spatial']}|evidence_ids(scenario)
                valid.update(p['plan_id'] for p in catalog(run['rounds'],budget))
                actions,notes=normalise_actions(actions,valid)
                candidate=apply_actions(spec,actions,geom,budget,physics_reference=physics,plan_history=run['rounds'],scenario=scenario,spatial_evidence=evidence['spatial'],resource_calibration=resource_calibration)
                from .mechanisms import intervention_review
                from .targets import resolve_cluster_actions
                resolved=resolve_cluster_actions(actions,evidence['spatial'],scales(spec,geom)['global_surface_cell_metres'])
                decision['resolved_measured_actions']=resolved
                decision['mechanism_review']=intervention_review(spec,candidate,resolved,evidence)
                if stage=='snap' and snap_signature(candidate)==snap_signature(spec):raise ValueError('proposal leaves snap construction unchanged, including an unchanged reversion to the protected base')
                next_signature=('full',plan_signature(candidate)) if native_mode=='full' else (('layers',plan_signature(candidate)) if any(a['snap_signature']==snap_signature(candidate) for a in anchors) else ('snap',snap_signature(candidate)))
                if next_signature in seen:
                    raise ValueError('proposed native stage already measured')
                spec=candidate;decision['executed_actions']=actions;decision['normalisation']=notes
            except (ValueError,KeyError,TypeError) as exc:
                run['stop_reason']='proposal rejected without spending a native stage: '+str(exc);run['rejected_decision']=decision;break
        run['selected']=max(archive,key=lambda a:(clear_gain(a,baseline),a['coverage'],-a['cells'])) if archive else None
        selected=run['selected']
        run['clear_gain_vs_one_shot']=clear_gain(selected,baseline)
        run['status']='completed' if selected else 'failed'
        run['accepted']=bool(selected)
        run['production_accepted']=any(r['stage'] in ('layers','full') and r['accepted'] for r in run['rounds'])
        run.setdefault('stop_reason','stage budget exhausted')
    except Exception as exc:
        run.update(status='failed',stop_reason=f'{type(exc).__name__}: {exc}')
    persist();return run
