from __future__ import annotations
import copy
import json
import time
from pathlib import Path
from .geometry import prepare,fidelity
from .planning import initial_plan,certify,apply_actions,deterministic_actions,finest_size,preflight_replan
from .runner import run_round
from .verify import spatial_diagnostics,layer_report
from .scientific_advisor import request_advice
from .scientific_tools import scales
from .planning import LAYER_PARAMETERS,SNAP_PARAMETERS,RESOLUTION_PARAMETERS,GENERATION_QUALITY_PARAMETERS,normalise_actions
from .io import write_json,read_json,sha256,code_hash
from .candidates import plan_signature,catalog,best_candidate,compact_catalog
from .handoff import handoff


def evaluate(result,geometry,case,spec,physics,budget,require_layers=True,scenario=None):
    measured_start=time.monotonic()
    quality=result.get('quality')
    reasons=list(quality['reasons']) if quality else ['no completed native checkMesh report']
    f=dict(available=False,accepted=False,reasons=['body boundary export unavailable'])
    layers=dict(available=False,accepted=False,reasons=['layers unavailable'])
    case=Path(case)
    if (case/'body.obj').exists():
        try: f=fidelity(geometry,case/'body.obj',finest_size(spec,geometry))
        except Exception as e: f['reasons']=[f'{type(e).__name__}: {e}']
        if require_layers:
            log=(case/'logs/snappyHexMesh.log').read_text(errors='replace')
            layers=layer_report(case,case/'body.obj',physics,log,spec.layers.expansion_ratio)
    if not f['accepted']: reasons+=f['reasons']
    if require_layers and not layers['accepted']: reasons+=layers['reasons']
    cells=(quality or {}).get('metrics',{}).get('cells')
    if cells is None or cells>budget: reasons.append('measured cell budget unavailable or exceeded')
    spatial,errors=spatial_diagnostics(case,geometry,spec,f.get('bad_surface_points'),layers.get('bad_layer_points'))
    if result.get('error'): reasons.append(result['error'])
    from .native_trace import wall_medial_snapshot
    native_wall_points=wall_medial_snapshot(case)
    write_json(case/'native_trace_summary.json',native_wall_points)
    scene_evidence=None
    if scenario:
        from .scenario import plan_screen,native_screen
        try:
            configured=plan_screen(spec,geometry,scenario)
            measured=native_screen(case,scenario)
            count_matches=cells is not None and measured['native_total_cells']==int(cells)
            scene_evidence=dict(accepted=configured['accepted'] and measured['accepted'] and count_matches,
                                configured=configured,native=measured,native_cell_count_consistent=count_matches)
        except Exception as e:
            scene_evidence=dict(accepted=False,available=False,error=f'{type(e).__name__}: {e}')
        if not scene_evidence['accepted']:reasons.append('off-body scenario resolution contract failed or measurement unavailable')
    return dict(accepted=not reasons,reasons=reasons,quality=quality,fidelity=f,
                scenario_screen=scene_evidence,scenario=scenario,
                layers=layers,spatial=spatial,spatial_unavailable=errors,
                fidelity_grade='sampled_geometry_verified' if f['accepted'] else 'unverified',
                rans_grade='near_wall_surrogate_verified' if require_layers and layers['accepted'] else 'unverified',
                physical_validation='unavailable_until_solver_validation',
                native_pre_limit_wall_points=native_wall_points,
                measurement_seconds=time.monotonic()-measured_start)


def run_agent(source,run_dir,of_root,budget=2_000_000,max_rounds=5,n_procs=1,
              advisor='none',scale=1.,round_seconds=900,total_seconds=3600,
              require_layers=True,flow=None,base_cells=8,initial_override=None,flow_probe=False,model_plan=False,probe_startup=0,resume_from=None,scenario_context=None,centre_geometry=False):
    run_dir=Path(run_dir)
    if (run_dir/'manifest.json').exists() or (run_dir/'input').exists():
        raise FileExistsError('output root already used; choose a fresh versioned run directory')
    run_dir.mkdir(parents=True,exist_ok=True)
    start=time.monotonic();before=sha256(source)
    result=dict(status='running',accepted=False,rounds=[],best_round=None,
                geometry=str(source),source_sha256=before,code_sha256=code_hash(),
                config=dict(budget=budget,max_rounds=max_rounds,n_procs=n_procs,advisor=advisor,
                            scale_to_metres=scale,round_seconds=round_seconds,total_seconds=total_seconds,
                            require_layers=require_layers,flow=flow,base_cells=base_cells,flow_probe=flow_probe,model_plan=model_plan,probe_startup=probe_startup,resume_from=str(resume_from) if resume_from else None,scenario_context=scenario_context,centre_geometry=centre_geometry),
                evidence_counts=dict(stl=0,mesh=0,cfd_force=0,field=0))
    write_json(run_dir/'agent_run.json',result)
    def persist():
        result['seconds']=time.monotonic()-start
        result['source_mutated']=sha256(source)!=before
        write_json(run_dir/'agent_run.json',result)
        write_json(run_dir/'handoff.json',handoff(result))
        write_json(run_dir/'manifest.json',dict(purpose='whole-body physics-aware scientific meshing',
               status=result['status'],source_sha256=before,code_sha256=result['code_sha256'],
               source_mutated=result['source_mutated'],disposition=result.get('stop_reason','in progress')))
    try:
        if not 1<=max_rounds<=5: raise ValueError('max-rounds must be in 1..5')
        parent=None;parent_case=None;parent_record=None
        if resume_from:
            parent=read_json(Path(resume_from)/'agent_run.json')
            if parent['status']=='running':raise ValueError('cannot resume an active episode')
            if parent['source_sha256']!=before or parent.get('source_mutated'):
                raise ValueError('resume source mismatch or source was mutated')
            retention=Path(resume_from)/'RETENTION.json'
            if retention.exists() and not read_json(retention).get('native_artifacts_available_for_resume',False):
                raise ValueError('resume native artifacts were archived during storage compaction; restore the retained snapshot; attempt and API budgets remain cumulative')
            if parent.get('config',{}).get('centre_geometry',False)!=centre_geometry:
                raise ValueError('resume coordinate-origin profile mismatch')
            prior=len(parent['rounds'])+parent.get('prior_mesh_attempts',0)
            if not prior or prior+max_rounds>5:raise ValueError('resume exceeds five mesh attempts including parent history')
            result['prior_mesh_attempts']=prior
            result['resume_parent_sha256']=sha256(Path(resume_from)/'agent_run.json')
            parent_record=parent['rounds'][-1];parent_case=Path(resume_from)/f'round{parent_record["round"]}'
            if parent['config']['budget']!=budget:raise ValueError('resume cell budget mismatch')
        try:
            geometry=prepare(source,run_dir/'input',scale=scale,centre_geometry=centre_geometry)
        except ValueError as e:
            result['surface_eligibility']=dict(accepted=False,stage='geometry_preparation',reasons=[str(e)])
            write_json(run_dir/'input_contract.json',result['surface_eligibility'])
            result.update(status='blocked',stop_reason='input eligibility rejected before paid planning: '+str(e))
            persist();return result
        result['evidence_counts']['stl']=1
        # Eligibility precedes paid scientific planning and every mesh attempt.
        from .runner import command,environment
        from .verify import surface_report
        step,text=command([Path(of_root)/'bin/surfaceCheck','-checkSelfIntersection','body.stl'],
                          run_dir/'input',environment(of_root),run_dir/'input/nativeSurfaceCheck.log',
                          min(start+total_seconds,time.monotonic()+300))
        eligible=surface_report(text,step['returncode']);eligible['step']=step
        result['surface_eligibility']=eligible
        write_json(run_dir/'input_contract.json',dict(accepted=eligible['accepted'],stage='native_surface_check',
                   source_sha256=before,canonical_sha256=geometry.canonical_hash,
                   scale_to_metres=scale,coordinate_frame=geometry.audit['coordinate_frame'],
                   semantic_parts_used=False,geometry_audit=geometry.audit,native_surface_check=eligible))
        if not eligible['accepted']:
            result.update(status='blocked',stop_reason='input eligibility rejected before paid planning: '+'; '.join(eligible['reasons']))
            persist();return result
        spec,physics=initial_plan(geometry,budget,base_cells,flow,require_layers,
                                 flow_length=float(geometry.mesh.extents[0]) if scenario_context else None)
        from .scenario import compile_scenario,evidence_ids,prior_actions,flow_region,plan_screen
        scenario=compile_scenario(scenario_context,geometry,physics) if scenario_context else None
        result['scenario']=scenario
        if scenario:write_json(run_dir/'scenario_contract.json',scenario)
        if parent:
            if (parent.get('scenario') or {}).get('contract_sha256')!=(scenario or {}).get('contract_sha256'):
                raise ValueError('resume scenario contract mismatch')
            if parent['flow']!=physics or parent['config']['require_layers']!=require_layers or parent['config']['scale_to_metres']!=scale:
                raise ValueError('resume physical contract mismatch')
            from .case_builder import MeshSpec
            spec=MeshSpec.from_dict(parent_record['spec'])
        elif initial_override:
            from .case_builder import MeshSpec
            spec=MeshSpec.from_dict(initial_override)
        else:
            if scenario and not model_plan:
                for action in prior_actions(spec,geometry,scenario):
                    spec.regions.append(flow_region(spec,action,geometry,scenario))
            spec,preflight=preflight_replan(spec,geometry,budget)
            write_json(run_dir/'preflight.json',preflight)
        result['geometry_audit']=geometry.audit;result['flow']=physics;persist()
        history=copy.deepcopy(parent.get('candidate_history',parent['rounds'])) if parent else []
        result['candidate_history']=history
        inherited_plans=catalog(history,budget);inherited_best=best_candidate(inherited_plans)
        result['best_provisional_candidate']=inherited_best
        write_json(run_dir/'candidate_catalog.json',inherited_plans)
        if inherited_best:write_json(run_dir/'best_candidate_spec.json',inherited_best['spec'])
        seen=set()
        if parent:
            seen.update(plan_signature(json.loads(s)) for s in parent.get('prior_plan_signatures',[]))
            seen.update(plan_signature(r['spec']) for r in history)
        result['prior_plan_signatures']=sorted(seen)
        decision=dict(source='explicit_initial_spec' if initial_override else 'geometry_plan',hypothesis='explicit reference scheme' if initial_override else 'measure features before meshing')
        if model_plan and advisor=='deepseek-flash':
            try:
                from .render import spatial_image
                spatial_image(geometry,parent_record['evidence'].get('spatial',[]) if parent else [],run_dir/'input/geometry.png',initial=not bool(parent),scenario=scenario)
            except Exception as e:
                write_json(run_dir/'input/image_unavailable.json',{'error':str(e)})
            initial=dict(stage='before first mesh; no native failure evidence yet',geometry=geometry.audit,
                         current_spec=spec.to_dict(),flow=physics,budget=budget,
                         physical_scales=scales(spec,geometry),
                         initial_certification=certify(spec,geometry,budget),
                         parameter_schema=dict(layer_settings=LAYER_PARAMETERS,snap_settings=SNAP_PARAMETERS,resolution_settings=RESOLUTION_PARAMETERS,generation_quality=GENERATION_QUALITY_PARAMETERS))
            initial['scenario']=scenario
            initial['scenario_screen']=plan_screen(spec,geometry,scenario) if scenario else None
            context_evidence={};initial_ids={'geometry'}|evidence_ids(scenario)
            if parent:
                initial.update(copy.deepcopy(parent_record['evidence']))
                initial['fidelity'].pop('bad_surface_points',None);initial['layers'].pop('bad_layer_points',None)
                initial['stage']='resume measured episode; original first-height estimate is a planning surrogate, not an immutable dimension'
                initial['parent_model_stop']=parent.get('advisor_stop',{}).get('decision')
                initial['remaining_mesh_attempts']=max_rounds
                context_evidence=parent_record['evidence']
                initial_ids={d['id'] for d in context_evidence['spatial']}|{'geometry','layers','quality','fidelity','physics'}|evidence_ids(scenario)
                initial['candidate_catalog']=compact_catalog(catalog(history,budget))
                initial_ids.update(p['plan_id'] for p in initial['candidate_catalog'])
            proposal,receipt=request_advice(run_dir,-1,initial,
                         timeout=min(750,max(1,total_seconds-(time.monotonic()-start))),
                         tool_context=dict(geometry=geometry,spec=spec,evidence=context_evidence,case=parent_case,budget=budget,physics=physics,plan_history=history,scenario=scenario))
            decision=dict(source='geometry_plan',advisor=proposal,receipt=receipt)
            if proposal and proposal.get('disposition')=='stop' and not proposal.get('actions'):
                result.update(status='blocked',stop_reason='model declined initial plan: '+str(proposal['hypothesis']),advisor_stop=decision)
                persist()
                from .experience import observations
                observations(result,run_dir/'experience.json');return result
            try:
                actions=(proposal or {}).get('actions')
                if actions:
                    actions,notes=normalise_actions(actions,initial_ids)
                    decision['interface_normalisation']=notes
                    spec=apply_actions(spec,actions,geometry,budget,physics_evidence=context_evidence.get('flow_probe'),physics_reference=physics,plan_history=history,scenario=scenario,spatial_evidence=context_evidence.get('spatial',[]))
                    decision.update(source='deepseek-flash_initial_plan',executed_actions=actions)
            except (ValueError,KeyError,TypeError) as e:decision['rejected_advisor']=str(e)
        result['initial_decision']=decision
        persist()
        for index in range(max_rounds):
            signature=plan_signature(spec)
            if signature in seen:
                advisor_error=(decision.get('receipt') or {}).get('error')
                result['stop_reason']=(f'advisor unavailable ({advisor_error}); ' if advisor_error else '')+'repeated plan blocked without spending another meshing round';break
            seen.add(signature)
            certification=certify(spec,geometry,budget)
            if scenario:
                screen=plan_screen(spec,geometry,scenario)
                certification['scenario_screen']=screen
                if not screen['accepted']:
                    certification['ok']=False;certification['reasons'].append('configured off-body scenario coverage is insufficient')
            if not certification['ok']:
                result['stop_reason']='preflight certification rejected: '+'; '.join(certification['reasons'])
                result['blocked_certification']=certification;break
            if time.monotonic()-start>=total_seconds:
                result['stop_reason']='total run time budget exhausted';break
            case=run_dir/f'round{index}'
            native=run_round(spec,geometry.path,case,of_root,n_procs,round_seconds,budget,start+total_seconds)
            evidence=evaluate(native,geometry,case,spec,physics,budget,require_layers,**({'scenario':scenario} if scenario else {}))
            if evidence['accepted'] and flow_probe and require_layers:
                from .physics import mesh_flow_probe
                try:
                    remaining=max(1,min(300,total_seconds-(time.monotonic()-start)))
                    probe=mesh_flow_probe(case,case/'flow_probe',physics,geometry.mesh.extents,of_root,n_procs,100,remaining,startup_steps=probe_startup)
                except Exception as e:
                    probe=dict(near_wall_probe_accepted=False,error=f'{type(e).__name__}: {e}')
                evidence['flow_probe']=probe
                result['evidence_counts']['cfd_force']+=probe.get('evidence_counts',{}).get('cfd_force',0)
                result['evidence_counts']['field']+=probe.get('evidence_counts',{}).get('field',0)
                if not probe['near_wall_probe_accepted']:
                    evidence['accepted']=False
                    evidence['reasons'].append('short flow probe rejected numerical sanity or actual near-wall y+ coverage')
                else:evidence['rans_grade']='short_flow_probe_verified_accuracy_unverified'
            record=dict(round=index,spec=spec.to_dict(),decision=decision,certification=certification,
                        native=native,evidence=evidence,accepted=evidence['accepted'])
            result['rounds'].append(record)
            history.append(dict(round=index,spec=spec.to_dict(),native=dict(error=native.get('error'),case=str(case)),
                                evidence={key:copy.deepcopy(evidence[key]) for key in ('quality','fidelity','layers','reasons')}))
            history[-1]['evidence']['fidelity'].pop('bad_surface_points',None)
            history[-1]['evidence']['layers'].pop('bad_layer_points',None)
            result['candidate_history']=history
            result['prior_plan_signatures']=sorted(seen)
            plans=catalog(history,budget);best=best_candidate(plans)
            result['best_provisional_candidate']=best
            write_json(run_dir/'candidate_catalog.json',plans)
            if best:write_json(run_dir/'best_candidate_spec.json',best['spec'])
            if native.get('quality',{}): result['evidence_counts']['mesh']+=1
            write_json(case/'record.json',record);persist()
            try:
                from .render import spatial_image
                spatial_image(geometry,evidence['spatial'],case/'spatial.png',scenario=scenario)
            except Exception as e:
                record['render_error']=type(e).__name__
            if evidence['accepted']:
                result['accepted']=True;result['best_round']=index
                result['stop_reason']=f'accepted whole-body mesh at round {index}; physical accuracy remains unverified'
                write_json(run_dir/'best_spec.json',spec.to_dict());break
            if index==max_rounds-1:
                result['stop_reason']='five-round or requested round budget exhausted';break
            # No evidence means stop diagnostically, rather than inventing a spatial repair.
            if not (native.get('quality') or {}).get('verified'):
                result['stop_reason']='native pipeline failed before mesh-quality evidence: '+str(native.get('error'));break
            concise=copy.deepcopy(evidence)
            concise['fidelity'].pop('bad_surface_points',None)
            concise['layers'].pop('bad_layer_points',None)
            def priority(d):
                metric=d.get('metric','').lower()
                if d.get('cause')=='boundary_topology':return 0
                if any(s in metric for s in ('nonmanifold','zerovolume','negative','illegal','meshquality','nonortho','skew','highaspect')):return 0
                if d['cause']=='layer_shortfall':return 1
                if d['cause']=='fidelity_loss':return 2
                return 3
            concise['spatial_inventory']={tag:sum(d['metric']==tag for d in evidence['spatial'])
                                         for tag in {d['metric'] for d in evidence['spatial']}}
            # Keep at least the strongest cluster of each metric before additional clusters.
            ranked=sorted(evidence['spatial'],key=lambda d:(priority(d),-d['count']))
            unique=[];extra=[];tags=set()
            for d in ranked:
                if d['metric'] in tags:extra.append(d)
                else:unique.append(d);tags.add(d['metric'])
            concise['spatial']=(unique+extra)[:12]
            concise['spatial_omitted_clusters']=len(evidence['spatial'])-len(concise['spatial'])
            concise.update(geometry=dict(bbox=geometry.audit['bbox'].tolist(),
                                          feature_sizes=geometry.audit['feature_half_size'],
                                          frame=geometry.audit['coordinate_frame']),
                           current_spec=spec.to_dict(),budget=budget,physical_scales=scales(spec,geometry),flow=physics,
                           candidate_catalog=compact_catalog(plans),
                           parameter_schema=dict(layer_settings=LAYER_PARAMETERS,snap_settings=SNAP_PARAMETERS,resolution_settings=RESOLUTION_PARAMETERS,generation_quality=GENERATION_QUALITY_PARAMETERS),
                           action_schema=dict(local_refine={'min':'3 metre coordinates','max':'3 metre coordinates','level':'current surface level +1 or +2'},
                                 gap_refine={'min':'3 metres','max':'3 metres','minimum_cells':'3..8','start_level':'gap detection start','max_level':'within global+2; native outside-fluid gaps only'},
                                 restore_plan={'plan_id':'eligible measured anchor; FIRST, then a distinct intervention'},
                                 remove_region={'name':'one exact existing geometric region'},update_region={'name':'one existing inside box','min':'3 metres','max':'3 metres','level':'within global+2'},
                                 resolution_settings={'parameters':'bounded global/base allocation'},refinement_bands={'parameters':'inner_distance/outer_distance, metres, jointly certified'},
                                 surface_refine='GLOBAL +1 surface level, NO coordinates',
                                 layer_settings={'parameters':'bounded layer_parameters patch; planner chooses values'},
                                 snap_settings={'parameters':'bounded snap_parameters patch; planner chooses values'},
                                 generation_quality={'parameters':'construction constraints may only tighten; independent acceptance is immutable'},
                                 wall_height={'scale':'0.5..2 times ORIGINAL flat-plate height; only with numerically sane measured flow; must cite physics'},
                                 snap_smooth='increase bounded snap smoothing',transition='increase transition buffer',
                                 layer_smooth='increase layer smoothing and attempts',
                                 layer_trim='reduce total layer count by 1, minimum 5, preserve first height'),
                           history=[dict(round=r['round'],
                                         decision_source=r['decision']['source'],
                                         executed_actions=r['decision'].get('executed_actions'),
                                         advisor_rejected=r['decision'].get('rejected_advisor'),
                                         cells=(r['evidence'].get('quality') or {}).get('metrics',{}).get('cells'),
                                         native_failed_checks=(r['evidence'].get('quality') or {}).get('n_failed'),
                                         layer_coverage=r['evidence']['layers'].get('coverage'),
                                         model_hypothesis=(r['decision'].get('advisor') or {}).get('hypothesis'),
                                         flow_probe_sanity=r['evidence'].get('flow_probe',{}).get('numerical_sanity'),
                                         actual_yplus=r['evidence'].get('flow_probe',{}).get('actual_yplus_distribution'),
                                         reasons=r['evidence']['reasons']) for r in result['rounds']])
            model_decision=None;receipt=None
            if advisor=='deepseek-flash':
                model_decision,receipt=request_advice(run_dir,index,concise,
                          timeout=min(750,max(1,total_seconds-(time.monotonic()-start))),
                          tool_context=dict(geometry=geometry,spec=spec,evidence=evidence,case=case,budget=budget,physics=physics,plan_history=history,scenario=scenario))
            if model_decision and model_decision.get('disposition')=='stop' and not model_decision.get('actions'):
                result['stop_reason']='model stopped with scientific evidence: '+str(model_decision['hypothesis'])
                result['advisor_stop']=dict(decision=model_decision,receipt=receipt);break
            proposals=(model_decision or {}).get('actions')
            decision=dict(source='deepseek-flash' if proposals else 'deterministic_fallback',
                          advisor=model_decision,receipt=receipt,advisor_unavailable=(receipt or {}).get('error'))
            if proposals:
                valid_ids={d['id'] for d in evidence['spatial']}|{'geometry','quality','layers','fidelity','physics'}|{p['plan_id'] for p in plans}|evidence_ids(scenario)
                try:
                    proposals,notes=normalise_actions(proposals,valid_ids)
                    decision['interface_normalisation']=notes
                except (ValueError,TypeError,KeyError) as e:
                    decision['rejected_advisor']=str(e);decision['source']='deterministic_fallback';proposals=None
            try:
                fallback=deterministic_actions(evidence,spec,geometry)
                if best and (evidence.get('quality') or {}).get('metrics',{}).get('min_volume',1)<=0:
                    fallback=[dict(kind='restore_plan',plan_id=best['plan_id'],why='nonpositive volumes: preserve a measured native-quality and geometry valid anchor before a distinct shrinker experiment',evidence=['quality',best['plan_id']]),
                              dict(kind='layer_settings',parameters=dict(mesh_shrinker='displacementMotionSolver' if best['spec']['layers']['mesh_shrinker']=='displacementMedialAxis' else 'displacementMedialAxis',n_outer_iter=1),why='test alternate mesh displacement with a single layer pass; not a general success rule',evidence=['quality','layers'])]
                chosen_actions=proposals or fallback
                spec=apply_actions(spec,chosen_actions,geometry,budget,physics_evidence=evidence.get('flow_probe'),physics_reference=physics,plan_history=history,scenario=scenario,spatial_evidence=evidence.get('spatial',[]))
                decision['executed_actions']=chosen_actions
            except (ValueError,KeyError,TypeError) as e:
                decision['rejected_advisor']=str(e)
                decision['source']='deterministic_fallback'
                fallback_sets=[fallback]
                if require_layers and not evidence['layers'].get('accepted'):
                    fallback_sets += [[dict(kind='layer_trim',why='reduce extrusion stack without spending cells on another refinement box',evidence=['layers']),
                                       dict(kind='layer_smooth',why='actual deficient-layer evidence; improve extrusion normals',evidence=['layers'])]]
                decision['fallback_rejections']=[]
                for fallback_actions in fallback_sets:
                    try:
                        repaired=apply_actions(spec,fallback_actions,geometry,budget,plan_history=history,scenario=scenario)
                        if plan_signature(repaired) in seen:
                            raise ValueError('fallback produces a previously tested plan')
                        spec=repaired;decision['executed_fallback']=fallback_actions
                        decision['executed_actions']=fallback_actions;break
                    except (ValueError,KeyError,TypeError) as fallback:
                        decision['fallback_rejections'].append(str(fallback))
                else:
                    result['stop_reason']='no certified repair within budget: '+'; '.join(decision['fallback_rejections']);break
        result['status']='completed' if result['accepted'] else ('failed' if result['rounds'] else 'blocked')
    except Exception as e:
        result['status']='failed';result['stop_reason']=f'{type(e).__name__}: {e}'
    persist()
    from .experience import observations
    observations(result,run_dir/'experience.json')
    return result
