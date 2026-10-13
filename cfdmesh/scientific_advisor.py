from __future__ import annotations
import base64
import hashlib
import io
import json
import time
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from .io import read_json,write_json,sha256,code_hash
from .scientific_tools import TOOLS,execute_query,plan_tool
from .plan_validation import validate_plan

# Official API names and peak USD / million tokens, checked 2026-10-12.
# Keep the model, modality and billing contract together; never bill Pro as Flash.
MODELS={
    'deepseek-flash':dict(input_miss=.30,input_hit=.006,output=1.20,vision=True,
        weights='https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash'),
    'deepseek-v4-pro':dict(input_miss=1.32,input_hit=.044,output=3.96,vision=False,
        weights='https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813'),
}

SYSTEM='''You are the scientific planner of an OpenFOAM v2412 whole-body external-flow RANS meshing agent.
Use CFD and meshing knowledge to identify mechanisms, not just change a numerical score.
When scenario evidence is supplied, reason about off-body transport, separation, shear layers,
velocity deficit and lift-induced vortices as well as geometry. Scenario requirements are
planning hypotheses, NOT measured flow. Use flow_refine {name:flow_*,min,max,level} to create
or replace an off-body box anywhere INSIDE the domain; levels may be LOWER than the surface.
Cite scenario or exact flow_requirement:* IDs. Preview coverage and cell cost jointly.
An isotropic refinement increment halves cell width and costs approximately EIGHT times
as many cells in a fixed volume, not twice. No wake shear thickness or vortex core radius
has been measured before a flow solution: never invent cells-across-shear-layer counts.
The mesh must satisfy the immutable spatial requirements, but you choose alternative box
layouts, overlap and levels. Do not assume ground, moving belt, free surface, steady shedding
accuracy or flow convergence when the declared boundary environment does not support them.
Coordinates are metres, flow +X, vertical +Z. Source semantic parts are unavailable.
You may QUERY geometry, dihedral angles, fluid gaps, actual layers and native bad clusters;
Prefer cluster_refine {ids:[exact measured cluster IDs],level,padding_cells:0..2} for local repair:
the compute tool resolves each measured bbox exactly. Do not retype x/y/z from memory.
Measured cluster_refine may use up to surface+4 (absolute level9), subject to the
unchanged joint geometry and cell-budget certification. Handwritten local boxes
remain limited to surface+2. Justify the target width from actual local evidence.
you may PREVIEW bounded parameter changes and consult version-specific OpenFOAM references.
Use these tools when an unmeasured assumption would change the repair. Distinguish boundary
layer extrusion/corner/shrinking failures from underresolved geometry and transition defects.
Check exact physical scales; never substitute background cell size for refined surface size.
Keep solid normal-ray half-thickness, fluid gaps, wall distance and the shrinker's NATIVE
FLUID medial distance distinct. A solid tube radius is NOT the external fluid medial
distance. Zero finite outward-ray gaps does NOT prove there are no gaps; rays are directional.
Consider multiple hypotheses and counterevidence from previous interventions.
Cross-case experience consists of measured observations, not universal rules.
Never copy coordinates or face/cluster IDs between cases. Remeasure the current
geometry and preview a hypothesis under its unchanged physical contract.
When baseline_stage_comparison is present, explicitly compare the measured before-layer
and after-layer checks. It refers to the original controls; check whether your CURRENT
controls match. Do not blame a negative volume observed only after layers on snapping
without counterevidence. Defects already present before layers still need repair.
An expensive refinement preview does not exclude cell-neutral layer/shrinker/snap changes.
Only claim infeasibility for the specific proposals tested, not the entire action space.
If resource_calibration is present, the preview uses a measured same-source full-mesh
cost ratio with a fixed 2x planning margin. This corrects the old additive overestimate
for overlapping boxes and solid interiors. It is a heuristic, not a resource guarantee.
The native final cell count must still pass the unchanged cap; the runtime monitor can
terminate an oversized trial. Do not quote the old raw forecast as the active cost gate.
When layer_design is supplied, check original target-layer coverage and actual
stack compression as well as >=5 layers. Fewer requested layers alone do not
prove improvement; inferred first heights are not direct wall distances.
Query layer_support: exact requested stack, nominal local cells across finite outward hits,
and a two-opposing-stack thought experiment. These are geometric constraints, not native
medial distances. More refinement cannot create extrusion space. Use gap_refine with an
anonymous coordinate box and minimum_cells/start_level/max_level to resolve measured gaps;
this triggers native outside-fluid gap refinement only, caps levels and preserves geometry.
Preview reports intervention overlap, inactive controls and before/after stack thickness.
Do not repeat contained same-level boxes or propose only inactive absolute-height controls.
Treat boundary_topology as higher priority than a coverage gain; a spatial cause label is
a diagnostic hypothesis, not proof that increasing refinement will cure the defect.
Plans are reversible: restore_plan {plan_id} must be FIRST and reference an eligible
measured candidate. Then propose a distinct intervention. Inspect_plan retrieves its settings.
After restore, use the ANCHOR's layer_parameters as the baseline, not the current failed
spec. Preview shows layer_changes_after_restore and restored_anchor_scales explicitly.
update_region {name,min,max,level} and remove_region {name} modify geometric regions;
no body parts are removed. All gates and physical conditions remain unchanged.
If a layer intervention creates nonpositive cells, prefer a measured valid anchor
over accumulating boxes on an inverted mesh. Repeated identical plans are blocked.
nOuterIter partitions layers into outer-to-inner slices; it is NOT a generic retry count.
nGrow propagates NON-EXTRUSION to adjacent points and zeros their displacement/layers.
Increasing nGrow does NOT fill uncovered faces; it trades coverage for safer transitions.
Available actions: local_refine {min,max,level}; refinement_bands {parameters: inner_distance, outer_distance} in metres; layer_settings {parameters}; resolution_settings {parameters: surface_level, base_cells}; snap_settings
{parameters}; generation_quality {parameters} only TIGHTENS construction limits,
never acceptance; surface_refine (GLOBAL +1, no coordinate arguments); transition;
layer_smooth; layer_trim; snap_smooth. Use 1..4 actions. Every action requires kind, why,
evidence:[existing cluster IDs or geometry/quality/layers/fidelity/physics]. Parameter ranges are
supplied in evidence and via openfoam_reference. YOU choose the actual values and mechanism.
Evidence is a list of EXACT IDs, e.g. ["layers", "layer_shortfall:0"], not sentences or
metric values. Put your interpretation in why. Only layer_settings, snap_settings, generation_quality, refinement_bands and resolution_settings have
a parameters member; legacy actions layer_smooth/transition/layer_trim have NO parameters.
Initial deterministic certification may be infeasible; use resolution_settings jointly
with geometric local boxes to allocate cells. Lowering global level never loosens geometry
or quality gates: the complete proposal must still pass feature and actual fidelity checks.
Local_refine levels must be within +2 of the global surface level. wall_height {scale} may
calibrate first height to 0.5..2 times the ORIGINAL physics estimate ONLY after a numerically
sane measured flow field. It must cite physics and use actual y+ or wall shear; NEVER use
a divergent field. You may not change speed, viscosity, target y+, quality/fidelity gates,
or delete geometry. No source part
segmentation, no raw Dict/commands. Preview proposals when cost feasibility is uncertain.
Do not repeat a failed mechanism without a new causal reason. Tool queries do not mesh.
After queries call propose_mesh_plan with hypothesis, alternatives, counterevidence,
expected_change and actions. Supply actual numerical settings in each parameters object.
Do not merely mention intended settings in why. Final evidence IDs must come from its enum.
If evidence indicates no plausible certified repair, submit disposition=stop and actions=[].
Make expected_change measurable, state uncertainty, do not assert unmeasured CFD accuracy.
If flow_probe is present, it is a 100-iteration unvalidated RANS probe. Numerical blow-up
invalidates wall-shear interpretation; do not adjust first height based on such a field.
Provisional layer coverage does not override failed flow evidence. Improve mesh mechanisms
or state why no certified fix is plausible. Passing the probe is not physical validation.
The image is diagnostic; measured fields and native checks determine acceptance.'''


def request_advice(run_dir,round_index,evidence,timeout=750,tool_context=None):
    spool=Path(run_dir)/'advisor';spool.mkdir(exist_ok=True)
    write_json(spool/f'request_{round_index}.json',dict(round=round_index,evidence=evidence,
        request_id=sha256(Path(run_dir)/'input/body.stl')))
    response=spool/f'response_{round_index}.json';started=time.monotonic()
    while time.monotonic()-started<timeout:
        for req in spool.glob(f'tool_request_{round_index}_*.json'):
            reply=spool/req.name.replace('tool_request_','tool_response_')
            if reply.exists():continue
            data=read_json(req)
            try:
                if tool_context is None:raise ValueError('scientific context unavailable')
                answer=execute_query(data['name'],data['arguments'],tool_context)
            except Exception as e:answer=dict(error=f'{type(e).__name__}: {e}')
            write_json(reply,answer)
        if response.exists():
            answer=read_json(response);return answer.get('decision'),answer
        time.sleep(.5)
    return None,dict(error='advisor unavailable before wait deadline')


@contextmanager
def ledger_lock(path):
    import fcntl
    with Path(path).with_suffix('.lock').open('a') as file:
        fcntl.flock(file,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(file,fcntl.LOCK_UN)


def reserve(ledger,upper,max_calls,cost_limit,model='deepseek-flash'):
    with ledger_lock(ledger):
        state=read_json(ledger) if ledger.exists() else dict(calls=0,estimated_usd=0.,requests=[],scope='one independent case',model=model)
        if state['calls']>=max_calls or state['estimated_usd']+upper>cost_limit:return False
        state['calls']+=1;state['estimated_usd']+=upper;write_json(ledger,state)
        return True


def settle(ledger,reserved,spent,record):
    with ledger_lock(ledger):
        state=read_json(ledger);state['estimated_usd']+=spent-reserved
        state['requests'].append(record);write_json(ledger,state)


def prompt_token_ceiling(payload):
    """Bound text/schema bytes, reasoning replay and provider image tokens.

    Inline PNG base64 is transport, not tokenized text. Official vision docs
    cap each image at 1024 tokens; keep an extra 1024 protocol-token margin.
    """
    import copy
    text=copy.deepcopy(payload);images=0
    for message in text['messages']:
        content=message.get('content')
        if isinstance(content,list):
            for block in content:
                if block.get('type')=='image_url':
                    images+=1;block['image_url']={'url':'[image transport omitted]'}
                elif block.get('type')!='text':
                    raise ValueError('unrecognised multimodal block; cannot certify cost')
    return len(json.dumps(text).encode())+1024*images+1024


def cached_peak_charge(usage,model='deepseek-flash'):
    """USD budget ceiling, not an invoice. Flash pricing verified 2026-10-12.

    Cache usage is provider evidence. Unknown cache usage remains all-miss;
    unknown/failed requests retain their existing reservation.
    """
    prompt=usage['prompt_tokens'];out=usage['completion_tokens']
    hit=usage.get('prompt_cache_hit_tokens',usage.get('prompt_tokens_details',{}).get('cached_tokens',0))
    if not 0<=hit<=prompt or prompt<0 or out<0:raise ValueError('invalid provider token usage')
    if 'prompt_cache_miss_tokens' in usage and usage['prompt_cache_miss_tokens']!=prompt-hit:
        raise ValueError('provider cache usage inconsistent')
    rate=MODELS[model]
    return (hit*rate['input_hit']+(prompt-hit)*rate['input_miss']+out*rate['output'])/1e6


def budget_charge(state):
    """Reconcile legacy all-miss ceilings without altering historical receipts.

    Start with the full ledger, including pending/unknown reservations. Replace
    ONLY a documented successful Flash all-miss charge with its cached peak
    ceiling. Never release a timeout or DNS reservation without evidence.
    """
    total=state['estimated_usd']
    for record in state.get('requests',[]):
        if not record.get('usage') or record.get('model')!='deepseek-flash':continue
        old=record.get('usd_at_peak_price_ceiling')
        if old is None:continue
        new=cached_peak_charge(record['usage'])
        total-=max(0.,old-new)
    return max(0.,total)


def transport_failure_charge(error,reserved):
    """Only proven local DNS failures release a reservation; timeouts do not."""
    import socket
    import urllib.error
    if isinstance(error,urllib.error.URLError) and isinstance(error.reason,socket.gaierror):
        return 0.
    return reserved


def request_price_factor(start_unix,end_unix):
    """Verified Flash peak/off-peak schedule, with a 60s boundary margin.

    Treat every weekday peak window as peak, including holidays: this avoids
    guessing the legal-holiday calendar. Cross-date/unknown intervals stay peak.
    Reserve at peak before calling; discount only a completed definite interval.
    """
    from datetime import datetime,timezone
    import math
    if not math.isfinite(start_unix) or not math.isfinite(end_unix) or end_unix<start_unix:return 1.
    first=datetime.fromtimestamp(start_unix-60,timezone.utc);last=datetime.fromtimestamp(end_unix+60,timezone.utc)
    if first.date()!=last.date():return 1.
    if first.weekday()>=5:return .5
    midnight=first.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    lo=start_unix-60-midnight;hi=end_unix+60-midnight
    if any(lo<finish*3600 and hi>=begin*3600 for begin,finish in ((1,4),(6,10))):return 1.
    return .5


def final_preview(run_dir,round_index,turn,decision,deadline):
    """Run the final action bundle through the compute node's certified preview.

    This automatic read-only audit does not call the model or a mesher. The served
    production dialogue requires it; isolated API formatting fixtures can omit it.
    """
    if decision.get('disposition')=='stop':return dict(stopped=True)
    req=Path(run_dir)/'advisor'/f'tool_request_{round_index}_{turn}_final.json'
    rep=req.with_name(req.name.replace('tool_request_','tool_response_'))
    write_json(req,dict(name='preview_actions',arguments=dict(actions=decision['actions'])))
    until=min(deadline,time.monotonic()+50)
    while time.monotonic()<until and not rep.exists():time.sleep(.5)
    if not rep.exists():raise ValueError('final certified preview unavailable; no mesh authorised')
    answer=read_json(rep)
    if answer.get('error'):raise ValueError('final proposal rejected by compute preview: '+answer['error'])
    if not answer.get('certification',{}).get('ok') or not answer.get('physical_scales'):
        raise ValueError('final certified preview missing positive certification/scales')
    if answer.get('scenario_screen') is not None and not answer['scenario_screen']['accepted']:
        raise ValueError('final preview violates immutable scenario requirements')
    return answer


def correction_messages(evidence,assistant,responses,scientific_review=False):
    """Focused format/certification repair, preserving the submitted plan.

    Old verbose hypotheses and unrelated region boxes must not compete with the
    exact validation error. Values are corrected by the model, never auto-clamped.
    """
    spec=evidence.get('current_spec',{})
    facts={k:evidence[k] for k in ('geometry','physical_scales','flow','budget','scenario','spatial','stage','instructions') if k in evidence}
    facts['current_settings']={k:spec[k] for k in ('layers','snap','surface','quality','domain','features','base_cells','max_global_cells') if k in spec}
    facts['quality_metrics']=evidence.get('quality',{}).get('metrics',{})
    facts['history_native_quality']=[dict(round=x.get('round'),native_failed_checks=x.get('native_failed_checks')) for x in evidence.get('history',[]) if 'native_failed_checks' in x]
    task=('Review this PROVISIONAL plan against the actual compute preview below before final commitment. Correct unsupported physical claims and units; distinguish resolution proxies, wall distance, outward-ray gap and native FLUID medial distance. If an observed risk fraction did not decrease, do not claim it decreased. Requested minimum gap cells and maximum levels are targets/caps, not a guaranteed native result. Cell forecasts are uncalibrated, not observed gains. Preserve unaffected numerical controls. Do not silently introduce a new base-cell/global resolution setting then quote the previous forecast or cell widths: every such change requires recomputation and can exceed the unchanged budget. Address feature-attraction warnings; change the plan or explain residual uncertainty. Acknowledge remaining topology failures; stop explicitly if no justified repair remains. Submit ONE final propose_mesh_plan; no additional queries in this review turn.' if scientific_review else
          'Correct ONLY the submitted final plan using the exact errors below and the tool schema. Preserve unaffected actions, values, coordinates and scientific hypotheses. Do not invent measurements or loosen acceptance. Return ONE propose_mesh_plan; stop explicitly if no certified correction is possible.')
    return [dict(role='system',content=SYSTEM),dict(role='user',content=task+'\n'+json.dumps(facts)),
            {k:v for k,v in assistant.items() if k in ('role','content','tool_calls')},*responses,
            dict(role='user',content='Submit the corrected final plan now. No more measurement queries.')]


def compact_model_evidence(evidence):
    """Remove duplicated plan prose, retaining exact numeric controls and all observations.

    The original request remains on disk. This view changes neither the tool
    context, acceptance rules, nor the executable specification.
    """
    import copy
    result=copy.deepcopy(evidence)
    for key in ('current_spec','last_tested_spec'):
        spec=result.get(key)
        if not isinstance(spec,dict):continue
        spec.pop('rationale',None)
        spec['regions']=[{k:v for k,v in r.items() if k!='why' and v is not None}
                         for r in spec.get('regions',[])]
    if result.get('last_tested_spec')==result.get('current_spec') and 'current_spec' in result:
        result['last_tested_spec']={'same_as_current_spec':True}
    elif isinstance(result.get('current_spec'),dict) and isinstance(result.get('last_tested_spec'),dict):
        current=result['current_spec'];last=result['last_tested_spec']
        delta={k:v for k,v in last.items() if k!='regions' and v!=current.get(k)}
        old_regions={r['name']:r for r in current.get('regions',[])}
        new_regions={r['name']:r for r in last.get('regions',[])}
        if old_regions!=new_regions:
            delta['regions']=dict(added_or_changed=[r for k,r in new_regions.items() if old_regions.get(k)!=r],
                removed_names=[k for k in old_regions if k not in new_regions])
        result['last_tested_spec']={'diff_from_current_spec':delta,
            'meaning':'exact tested values replace current values; unchanged fields and regions inherit current'}
    shared={}
    for item in result.get('spatial',[]):
        for key in ('cause_status','feature_quantity'):
            if key in item:
                value=item.pop(key);shared.setdefault(key,[])
                if value not in shared[key]:shared[key].append(value)
    if shared:result['spatial_interpretations']=shared
    result=compact_region_tables(result)
    result['proposal_claims']='Model hypotheses and forecasts are unverified until independent native evaluation.'
    return result


def compact_region_tables(value):
    """Lossless columnar view of large automatic region inventories; no rounding.

    Original requests and compute receipts remain conventional JSON on disk.
    This affects only the model's text view, including query observations.
    """
    if isinstance(value,list):return [compact_region_tables(x) for x in value]
    if not isinstance(value,dict):return value
    result={k:compact_region_tables(v) for k,v in value.items()}
    regions=value.get('regions')
    if isinstance(regions,list) and len(regions)>12 and all(isinstance(r,dict) and 'name' in r and 'shape' in r for r in regions):
        rows=[{k:v for k,v in r.items() if k!='why' and v is not None} for r in regions]
        columns=sorted({k for r in rows for k in r})
        result['regions']=dict(encoding='columns/rows: exact values; null means absent; names identify regions',
            columns=columns,rows=[[r.get(k) for k in columns] for r in rows])
    return result


def commitment_messages(evidence,messages):
    """A bounded final view: exact global controls, measured targets and tool receipts.

    All region coordinates remain in the original request and compute context.
    Large unchanged inventories need not be repeated to format a committed plan.
    """
    facts={k:evidence[k] for k in ('geometry','physical_scales','flow','budget','scenario','spatial','spatial_interpretations',
        'stage','instructions','quality','layer_design','baseline_stage_comparison','resource_calibration','baseline') if k in evidence}
    spec=evidence.get('current_spec',{})
    facts['current_settings']={k:v for k,v in spec.items() if k not in ('regions','rationale')}
    regions=spec.get('regions',[])
    facts['region_inventory']=dict(retained_in_compute_context=True,count=len(regions.get('rows',[])) if isinstance(regions,dict) else len(regions))
    facts['candidate_catalog']=evidence.get('candidate_catalog',[])
    facts['checkpoint_unavailable_calls']=(evidence.get('resume_visible_queries') or {}).get('unavailable_calls',[])
    receipts=[]
    for message in messages:
        if message.get('role') in ('assistant','tool'):
            m={k:v for k,v in message.items() if k!='reasoning_content'}
            if m.get('role')=='tool':
                try:m['content']=json.dumps(compact_region_tables(json.loads(m['content'])),separators=(',',':'))
                except (ValueError,TypeError):pass
            receipts.append(m)
    return [dict(role='system',content=SYSTEM),dict(role='user',content='Commit one scientifically justified plan from this measured state. All original controls and regions remain in the compute preview; unchanged region inventories are omitted here.\n'+json.dumps(facts,separators=(',',':'))),
        *receipts,dict(role='user',content='Submit ONE propose_mesh_plan now. Mandatory final compute preview still applies. No further paid queries; stop only with a specific measured reason.')]


def measured_receipt_memory(messages):
    """Formatting repairs retain measurements, not repeated reference/schema inventories."""
    names={c['id']:c['function']['name'] for m in messages if m.get('role')=='assistant' for c in m.get('tool_calls',[])}
    result=[]
    for m in messages:
        if m.get('role')!='tool' or not m.get('tool_call_id'):continue
        try:answer=json.loads(m['content'])
        except (ValueError,TypeError):answer={}
        keys=set(answer) if isinstance(answer,dict) else set()
        if names.get(m['tool_call_id'])=='openfoam_reference' and keys<=set(('reference','layer_parameters','snap_parameters','resolution_parameters','refinement_band_parameters','generation_quality_parameters')):continue
        if names.get(m['tool_call_id'])=='inspect_scenario' and keys<=set(('scenario','configured_screen','warning')):continue
        item={k:v for k,v in m.items() if k!='reasoning_content'}
        try:item['content']=json.dumps(compact_region_tables(json.loads(item['content'])),separators=(',',':'))
        except (ValueError,TypeError):pass
        result.append(item)
    return result


def scientific_dialogue(run_dir,request,key,ledger,max_calls,cost_limit,max_turns=4,max_output=32768,reasoning_effort='high',require_final_preview=False,query_turns=None,require_scientific_review=True,model='deepseek-flash'):
    if model not in MODELS:raise ValueError('unsupported model billing contract')
    rates=MODELS[model]
    if query_turns is not None and not 1<=query_turns<=max_turns-3:
        raise ValueError('adaptive query turns require three reserved commitment/repair/review turns')
    spool=Path(run_dir)/'advisor';round_index=request['round']
    model_evidence=compact_model_evidence(request['evidence'])
    user=json.dumps(model_evidence,ensure_ascii=False,separators=(',',':'))
    image_meta=dict(attached=False)
    image=Path(run_dir)/('input/geometry.png' if round_index==-1 else f'round{round_index}/spatial.png')
    if image.exists() and rates['vision']:
        from PIL import Image
        with Image.open(image) as im:
            im.thumbnail((1024,512));buffer=io.BytesIO();im.save(buffer,format='PNG')
        user=[dict(type='text',text=user),dict(type='image_url',image_url=dict(url='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),detail='low'))]
        image_meta=dict(attached=True,source_sha256=sha256(image),sent_png_sha256=hashlib.sha256(buffer.getvalue()).hexdigest(),sent_png_bytes=len(buffer.getvalue()),detail='low')
    messages=[dict(role='system',content=SYSTEM),dict(role='user',content=user)]
    checkpoint=request.get('resume_visible_queries') or request['evidence'].get('resume_visible_queries')
    if checkpoint:
        messages.extend(checkpoint['messages'])
        if checkpoint.get('unavailable_calls'):
            messages.append(dict(role='user',content='These previous calls have no complete computed receipt and must not be treated as measurements: '+json.dumps(checkpoint['unavailable_calls'])))
    query_count=sum(m.get('role')=='tool' for m in (checkpoint or {}).get('messages',[]));receipts=[];deadline=time.monotonic()+720;force_final=bool(checkpoint);repair=None;reviewed=False;reviewing=False
    if checkpoint and len(checkpoint['messages'])>=2:
        assistant,reply=checkpoint['messages'][-2:];calls=assistant.get('tool_calls',[])
        if assistant.get('role')=='assistant' and len(calls)==1 and calls[0]['function']['name']=='propose_mesh_plan' and reply.get('role')=='tool':
            repair=(assistant,[reply])
    for turn in range(max_turns):
        if deadline-time.monotonic()<10:
            return dict(error='scientific dialogue wall-time cap',receipts=receipts)
        final_tool=plan_tool(request['evidence'])
        # Leave one turn to correct a malformed final proposal. Corrections share
        # the same episode turn and cumulative monetary limits; they never mesh.
        final_start=query_turns if query_turns is not None else (max(0,max_turns-3) if require_final_preview else max(1,max_turns-2))
        available=TOOLS+[final_tool] if turn<final_start and query_count<8 and not force_final else [final_tool]
        if available==[final_tool]:
            messages.append(dict(role='user',content='The measurement/preview budget is now complete. Submit propose_mesh_plan NOW. Do not request another query or preview. Use measured evidence, include numerical settings in parameters, keep the final plan concise (under 1500 words). This final call does not execute a mesh.'))
        effort=reasoning_effort
        active_messages=correction_messages(model_evidence,*repair,scientific_review=reviewing) if repair else messages
        if available==[final_tool] and not repair:active_messages=commitment_messages(model_evidence,messages)
        if repair and query_turns is not None:
            memory=measured_receipt_memory(messages)
            active_messages.insert(1,dict(role='user',content='Retained measured tool receipts from this decision (these are observations, not causal proof):\n'+json.dumps(memory)))
        # Final-format/review calls have thinking disabled and a concise plan.
        # Reserving a full reasoning budget here can falsely block commitment
        # despite enough money for the actual bounded final interface.
        output_ceiling=min(max_output,4096) if available==[final_tool] else max_output
        payload=dict(model=model,messages=active_messages,max_tokens=output_ceiling,tools=available,
            thinking={'type':'enabled'},reasoning_effort=effort)
        if available==[final_tool]:
            # Official API forbids named tool_choice in thinking mode. Final formatting
            # uses existing measurements, bounded tokens, and an actual named tool call.
            payload['thinking']={'type':'disabled'};payload.pop('reasoning_effort')
            payload['tool_choice']={'type':'function','function':{'name':'propose_mesh_plan'}}
            payload['messages']=[{k:v for k,v in m.items() if k!='reasoning_content'} for m in active_messages]
            effort='disabled-final-format'
        encoded=json.dumps(payload).encode()
        input_ceiling=prompt_token_ceiling(payload)
        if available==[final_tool]:
            import math
            remaining=cost_limit-budget_charge(read_json(ledger)) if Path(ledger).exists() else cost_limit
            affordable=math.floor((remaining-input_ceiling*rates['input_miss']/1e6-.000002)*1e6/rates['output'])
            if 1024<=affordable<output_ceiling:
                output_ceiling=affordable;payload['max_tokens']=output_ceiling
                encoded=json.dumps(payload).encode();input_ceiling=prompt_token_ceiling(payload)
        upper=(input_ceiling*rates['input_miss']+output_ceiling*rates['output'])/1e6
        if not reserve(ledger,upper,max_calls,cost_limit,model):
            return dict(error='per-case call/cost cap prevents another request',receipts=receipts,
                required_peak_reservation_usd=upper,run_cost_limit=cost_limit,
                remaining_run_usd=cost_limit-budget_charge(read_json(ledger)) if Path(ledger).exists() else cost_limit)
        start=time.monotonic();spent=upper;settled=False
        actually_has_image=any(isinstance(m.get('content'),list) and any(b.get('type')=='image_url' for b in m['content']) for m in payload['messages'])
        actual_image_meta=image_meta if actually_has_image else dict(attached=False,reason='compact final/correction text or no supported image')
        record=dict(round=round_index,turn=turn,request_sha256=hashlib.sha256(encoded).hexdigest(),advisor_code_sha256=code_hash(),request_bytes=len(encoded),image_input=actual_image_meta,
                    request_started_unix=time.time(),api_endpoint='https://api.deepseek.com/chat/completions',credential_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
                    reserved_input_token_ceiling=input_ceiling,reserved_output_tokens=output_ceiling,reserved_usd=upper,
                    requested_model=model,peak_usd_per_million_tokens=rates,
                    reservation_basis='UTF8 text/schema bytes +1024/image +1024 protocol; official pricing checked 2026-10-12; cache-miss peak reservation ceiling, not invoice')
        try:
            call=urllib.request.Request('https://api.deepseek.com/chat/completions',data=encoded,
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            with urllib.request.urlopen(call,timeout=min(240,deadline-time.monotonic())) as http:raw=json.load(http)
            usage=raw.get('usage')
            if usage is None:raise ValueError('provider token usage unavailable')
            peak_spent=cached_peak_charge(usage,model)
            end_unix=time.time();factor=request_price_factor(record['request_started_unix'],end_unix)
            spent=peak_spent*factor
            if usage['prompt_tokens']>input_ceiling or usage['completion_tokens']>output_ceiling:
                raise ValueError('provider exceeded certified token ceiling; stop paid dialogue')
            message=raw['choices'][0]['message'];finish=raw['choices'][0].get('finish_reason')
            record.update(usage=usage,provider_response_id=raw.get('id'),request_finished_unix=end_unix,pricing_window_factor=factor,
                usd_at_peak_price_ceiling=peak_spent,budget_charge_usd=spent,billing_basis='cache-aware USD rate ceiling for observed interval; holidays remain conservative; not invoice',seconds=time.monotonic()-start,
                finish_reason=finish,reasoning_mode=effort,model=raw.get('model'),
                reasoning_sha256=hashlib.sha256((message.get('reasoning_content') or '').encode()).hexdigest())
            settle(ledger,upper,spent,record);settled=True;receipts.append(record)
            # The provider requires reasoning replay with tools; keep it in memory, not public artifacts.
            messages.append({k:message[k] for k in ('role','content','reasoning_content','tool_calls') if k in message})
            calls=message.get('tool_calls')
            write_json(spool/f'public_answer_{round_index}_{turn}.json',dict(content=message.get('content'),tool_calls=calls))
            plans=[t for t in calls or [] if t['function']['name']=='propose_mesh_plan']
            if plans:
                if len(calls)!=1:
                    responses=[]
                    for tool in calls:
                        responses.append(dict(role='tool',tool_call_id=tool['id'],content=json.dumps(dict(error='Final plan must be the ONLY call. Consolidate into ONE propose_mesh_plan with at most four actions; do not submit multiple plans or mix final and query calls.',executed=False))))
                    messages.extend(responses);repair=(message,responses)
                    force_final=True
                    if turn<max_turns-1:continue
                    return dict(error='multiple final plans or mixed final/query calls',receipts=receipts)
                try:
                    decision=json.loads(plans[0]['function']['arguments'])
                    validate_plan(decision,final_tool)
                    preview=final_preview(run_dir,round_index,turn,decision,deadline) if require_final_preview else None
                except ValueError as exc:
                    responses=[dict(role='tool',tool_call_id=plans[0]['id'],content=json.dumps(dict(error=str(exc),executed=False)))]
                    messages.extend(responses);repair=(message,responses)
                    force_final=True;reviewing=False
                    if turn<max_turns-1:continue
                    return dict(error='final proposal invalid',validation_error=str(exc),receipts=receipts)
                if require_final_preview and require_scientific_review and not reviewed and decision.get('disposition')!='stop':
                    if turn>=max_turns-1:return dict(error='final scientific review budget exhausted; provisional plan not committed',receipts=receipts,provisional_preview=preview)
                    responses=[dict(role='tool',tool_call_id=plans[0]['id'],content=json.dumps(dict(status='provisional_requires_scientific_review',native_execution_authorised=False,compute_preview=preview)))]
                    messages.extend(responses);repair=(message,responses);force_final=True;reviewed=True;reviewing=True
                    continue
                return dict(decision=decision,receipts=receipts,tool_queries=query_count,thinking='enabled-'+reasoning_effort,final_interface='typed_function',final_certified_preview=preview,scientific_review_completed=reviewed)
            if not calls:
                if finish=='length':
                    if not force_final and turn<max_turns-1:
                        force_final=True
                        messages.append(dict(role='user',content='Your previous thinking reached the output cap. Submit one concise propose_mesh_plan now using the measurements already available, or stop with an explicit scientific reason. No further queries; do not invent measurements.'))
                        continue
                    return dict(error='model exhausted output limit',receipts=receipts)
                content=(message.get('content') or '{}').strip()
                if content.startswith('```'):
                    content=content.split('\n',1)[1].rsplit('```',1)[0].strip()
                try:
                    decision=json.loads(content)
                    validate_plan(decision,final_tool)
                    preview=final_preview(run_dir,round_index,turn,decision,deadline) if require_final_preview else None
                except ValueError as exc:
                    responses=[dict(role='user',content='Final plan was not executed. Correct this exact validation error and submit propose_mesh_plan: '+str(exc))]
                    messages.extend(responses);repair=(message,responses)
                    force_final=True;reviewing=False
                    if turn<max_turns-1:continue
                    return dict(error='final proposal invalid',validation_error=str(exc),receipts=receipts)
                if require_final_preview and require_scientific_review and not reviewed and decision.get('disposition')!='stop':
                    if turn>=max_turns-1:return dict(error='final scientific review budget exhausted; provisional plan not committed',receipts=receipts,provisional_preview=preview)
                    responses=[dict(role='user',content='Provisional plan not committed. Review the actual compute preview: '+json.dumps(preview))]
                    messages.extend(responses);repair=(message,responses);force_final=True;reviewed=True;reviewing=True
                    continue
                return dict(decision=decision,receipts=receipts,tool_queries=query_count,thinking='enabled-'+reasoning_effort,final_certified_preview=preview,scientific_review_completed=reviewed)
            for index,tool in enumerate(calls):
                if query_count>=8:answer={'error':'eight queries per decision reached'}
                else:
                    query_count+=1;name=tool['function']['name']
                    args=json.loads(tool['function'].get('arguments') or '{}')
                    req=spool/f'tool_request_{round_index}_{turn}_{index}.json'
                    rep=spool/req.name.replace('tool_request_','tool_response_')
                    write_json(req,dict(name=name,arguments=args));until=min(deadline,time.monotonic()+50)
                    while time.monotonic()<until and not rep.exists():time.sleep(.5)
                    answer=read_json(rep) if rep.exists() else {'error':'compute query timeout'}
                messages.append(dict(role='tool',tool_call_id=tool['id'],content=json.dumps(compact_region_tables(answer))))
        except Exception as e:
            if not settled:
                spent=transport_failure_charge(e,spent)
                record.update(error=type(e).__name__,error_detail=str(e),budget_charge_usd=spent,seconds=time.monotonic()-start)
                settle(ledger,upper,spent,record)
            return dict(error=type(e).__name__,error_detail=str(e),receipts=receipts)
    return dict(error='dialogue turn cap exhausted',receipts=receipts)


def budget_source_alias(source,aliases):
    import re
    if any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',k) or not re.fullmatch('[a-f0-9]{64}',v) for k,v in aliases.items()):
        raise ValueError('case budget source alias must reference exact SHA256 provenance')
    seen=set()
    while source in aliases:
        if source in seen:raise ValueError('cyclic case budget source alias')
        seen.add(source);source=aliases[source]
    return source


def geometry_spend(run_dir):
    run_dir=Path(run_dir).resolve();manifest=read_json(run_dir/'manifest.json');source=manifest['source_sha256']
    total=0.
    scope=run_dir.parent.parent/'api_budget_scope.json'
    roots=[run_dir.parent];aliases={}
    if scope.exists():
        config=read_json(scope);roots=list(dict.fromkeys([run_dir.parent]+[Path(p) for p in config['run_roots']]))
        aliases=config.get('source_aliases',{})
        if len(roots)>16 or any(not p.is_absolute() or not p.is_dir() for p in roots):raise ValueError('budget evidence roots invalid/unavailable')
    source=budget_source_alias(source,aliases)
    for sibling in (p for root in roots for p in root.iterdir()):
        m=sibling/'manifest.json';ledger=sibling/'advisor/usage.json'
        if m.exists() and ledger.exists() and budget_source_alias(read_json(m).get('source_sha256'),aliases)==source:
            total+=budget_charge(read_json(ledger))
    own=budget_charge(read_json(run_dir/'advisor/usage.json')) if (run_dir/'advisor/usage.json').exists() else 0.
    return source,total,own


def serve(run_dir,key_file,max_calls=24,cost_limit=.5,seconds=7200,case_cost_limit=.5,max_turns=4,max_output=32768,reasoning_effort='high',query_turns=None,review_policy='llm',model='deepseek-flash',**unused):
    if not 1<=max_turns<=10 or not 1024<=max_output<=32768:raise ValueError('invalid scientific dialogue limits')
    if reasoning_effort not in ('low','high','max'):raise ValueError('invalid scientific reasoning effort')
    if review_policy not in ('llm','program'):raise ValueError('invalid review policy')
    if model not in MODELS:raise ValueError('unsupported model billing contract')
    run_dir=Path(run_dir);spool=run_dir/'advisor';spool.mkdir(parents=True,exist_ok=True)
    ledger=spool/'usage.json';key=Path(key_file).read_text().strip();start=time.monotonic()
    while time.monotonic()-start<seconds:
        for req in sorted(spool.glob('request_*.json')):
            response=spool/req.name.replace('request_','response_')
            if response.exists():continue
            source,_,_=geometry_spend(run_dir)
            scope=run_dir.parent.parent/'api_budget_scope.json'
            locks=Path(read_json(scope)['lock_directory']) if scope.exists() else run_dir.parent.parent/'api_case_locks'
            locks.mkdir(parents=True,exist_ok=True)
            # Serialise paid decisions for the same source, including resumed/versioned runs.
            with ledger_lock(locks/source):
                source,total,own=geometry_spend(run_dir)
                allocated=min(cost_limit,max(0.,case_cost_limit-total+own))
                answer=scientific_dialogue(run_dir,read_json(req),key,ledger,max_calls,allocated,max_turns,max_output,reasoning_effort,require_final_preview=True,query_turns=query_turns,require_scientific_review=review_policy=='llm',model=model)
                answer['actor_model']=model
                answer['review_policy']=review_policy
                answer['case_budget']=dict(source_sha256=source,total_before=total,run_allocation=allocated,geometry_cap=case_cost_limit)
                write_json(response,answer)
        state=run_dir/'agent_run.json'
        if state.exists() and read_json(state).get('status') in ('completed','failed','blocked'):
            return read_json(ledger) if ledger.exists() else {'calls':0,'estimated_usd':0}
        time.sleep(1)
    return read_json(ledger) if ledger.exists() else {'calls':0,'estimated_usd':0}
