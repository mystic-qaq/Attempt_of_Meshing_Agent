"""Measured cross-case memory. Retrieval is a hypothesis aid, never mesh acceptance.

Only experiment outcomes enter this store. Coordinates and face/cluster IDs do
not transfer between geometries. Derived copies share their original source
group, so a wrapped clone cannot become its own held-out case.
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from .io import read_json,sha256,write_json


def descriptor(geometry,physics):
    ext=geometry['extents'];length=max(ext)
    height=physics['first_layer_height']
    return [ext[1]/ext[0],ext[2]/ext[0],height/length,
            geometry['feature_half_size']['p5']/length,
            geometry.get('finite_fluid_gap_fraction',0.)]


def portable_actions(actions,global_level):
    result=[]
    for action in actions or []:
        item={'kind':action['kind']}
        if 'parameters' in action:item['parameters']=copy.deepcopy(action['parameters'])
        if 'level' in action:item['relative_surface_level']=action['level']-global_level
        if 'padding_cells' in action:item['padding_cells']=action['padding_cells']
        if action['kind'] in ('local_refine','cluster_refine','gap_refine','update_region'):
            item['scope']='remeasure a corresponding defect on the NEW input; old coordinates and IDs deliberately omitted'
        result.append(item)
    return result


def collect(roots):
    facts=[]
    for root in map(Path,roots):
        protocol=read_json(root/'protocol.json')
        entries={c['source_sha256']:c for c in protocol['cases']}
        for run in sorted((root/'runs').glob('*')):
            if not (run/'agent_run.json').exists():continue
            data=read_json(run/'agent_run.json')
            if data['status']=='running':raise ValueError('memory may contain only terminal, immutable episodes')
            if data.get('source_mutated'):raise ValueError('mutated input cannot become experience')
            source=data['source_sha256'];entry=entries[source]
            group=entry.get('original_source_sha256',source)
            for row in data['rounds']:
                q=row['evidence'].get('quality') or {}
                layer=row['evidence'].get('layers') or {}
                record=run/f'round{row["round"]}'/'record.json'
                facts.append(dict(record_sha256=sha256(record),source_group_sha256=group,
                    mesher='OpenFOAM v2412',geometry_route=entry.get('geometry_route','original triangles'),
                    stage=row['stage'],descriptor=descriptor(data['geometry_audit'],data['flow']),
                    intervention=portable_actions(row['decision'].get('executed_actions'),row['spec']['surface']['level_max']),
                    decision_source=row['decision']['source'],quality_accepted=q.get('accepted',False),
                    basic_failed=q.get('n_failed'),cells=q.get('metrics',{}).get('cells'),
                    research_eligible=row['research_eligible'],coverage_ge5=layer.get('coverage'),
                    layer_design=row.get('layer_design'),reasons=[re.sub(r'boundary face \d+ bbox \[[^\]]*\] \.\. \[[^\]]*\]','boundary polygon (case coordinates omitted)',text) for text in row['evidence']['reasons']],
                    interpretation='one measured outcome; mechanism and generalization remain hypotheses'))
    # Re-reading the same measurement from multiple collections does not multiply support.
    return list({f['record_sha256']:f for f in facts}.values())


def full_baseline_facts(roots):
    """Measured full-mesh controls also inform later disjoint cases, without positive relabeling."""
    from .drivaer import research_eligible
    from .layer_design import measure_layer_design
    from .case_builder import MeshSpec
    result=[]
    for root in map(Path,roots):
        data=read_json(root/'agent_run.json')
        if data['status']=='running' or data.get('source_mutated'):raise ValueError('baseline is not immutable/terminal')
        for row in data['rounds']:
            q=row['evidence'].get('quality') or {}
            record=root/f'round{row["round"]}'/'record.json'
            result.append(dict(record_sha256=sha256(record),source_group_sha256=data['source_sha256'],
                mesher='OpenFOAM v2412',geometry_route='original triangles',stage='full',
                descriptor=descriptor(data['geometry_audit'],data['flow']),intervention=[],decision_source='pure program one-shot',
                quality_accepted=q.get('accepted',False),basic_failed=q.get('n_failed'),cells=q.get('metrics',{}).get('cells'),
                research_eligible=research_eligible(row['evidence'],row['native'],data['config']['budget']),
                coverage_ge5=row['evidence']['layers'].get('coverage'),
                layer_design=measure_layer_design(row['native']['case'],MeshSpec.from_dict(row['spec']),data['flow']),
                reasons=[re.sub(r'boundary face \d+ bbox \[[^\]]*\] \.\. \[[^\]]*\]','boundary polygon (case coordinates omitted)',t) for t in row['evidence']['reasons']],
                interpretation='complete native first mesh; rejected results remain negative observations'))
    return result


def retrieve(facts,geometry,physics,current_group,stage,geometry_route,allowed_training_groups=None,k=3):
    target=descriptor(geometry,physics);ranked=[]
    for fact in facts:
        group=fact['source_group_sha256']
        if group==current_group or fact['stage']!=stage or fact['geometry_route']!=geometry_route:continue
        if allowed_training_groups is not None and group not in allowed_training_groups:continue
        values=fact['descriptor']
        if len(values)!=len(target) or not all(math.isfinite(x) for x in values+target):continue
        # Ratios are unitless; floor only stabilizes genuinely near-zero features.
        distance=sum(abs(math.log((a+1e-9)/(b+1e-9))) for a,b in zip(values,target))/len(target)
        if distance<=1.5:ranked.append((distance,fact))
    result=[];groups=set()
    for distance,fact in sorted(ranked,key=lambda pair:pair[0]):
        if fact['source_group_sha256'] in groups:continue
        groups.add(fact['source_group_sha256'])
        related=[];mechanisms=set()
        for _,other in reversed(ranked):
            if other['source_group_sha256']!=fact['source_group_sha256']:continue
            signature=json.dumps(other.get('intervention'),sort_keys=True)
            if signature in mechanisms:continue
            mechanisms.add(signature);related.append(other)
            if len(related)==4:break
        result.append(dict(fact,descriptor_distance=distance,related_observations=related,
                           distinct_original_case_support=1))
        if len(result)==k:break
    return result


def promotion_check(training,validation):
    """A reusable policy requires distinct original cases and untouched validation.

    Inputs must come from independently measured paired comparisons. This helper
    does not generate evidence or train a model.
    """
    train={r['source_group_sha256'] for r in training};valid={r['source_group_sha256'] for r in validation}
    reasons=[]
    if len(train)<2:reasons.append('fewer than two distinct original training geometries')
    if not valid:reasons.append('no independent validation geometry')
    if train&valid:reasons.append('training/validation source groups overlap, including derived clones')
    for row in training+validation:
        if not row.get('baseline_research_eligible') or not row.get('candidate_research_eligible'):
            reasons.append('invalid native candidate or baseline')
        if not row.get('clear_gain') or not row.get('same_budget'):
            reasons.append('no verified gain in a matched-budget comparison')
    return dict(promoted=not reasons,reasons=sorted(set(reasons)),training_groups=sorted(train),validation_groups=sorted(valid))


def write_store(path,facts):
    if Path(path).exists():raise FileExistsError('experience snapshots are immutable')
    payload=dict(schema_version=1,facts=facts,positive_rules_promoted=0,
        training_source_groups=sorted({f['source_group_sha256'] for f in facts}),
        policy='measured facts only; no automatic promotion; no hidden reasoning; no cross-case coordinate reuse')
    payload['facts_sha256']=hashlib.sha256(json.dumps(facts,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    write_json(path,payload)
