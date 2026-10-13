from __future__ import annotations
import base64
import json
import os
import time
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from .io import read_json,write_json,sha256

SYSTEM = '''You are a scientific OpenFOAM v2412 external-flow RANS meshing advisor.
Use the whole watertight body; no semantic part segmentation or source part labels.
Diagnose from geometric coordinates, local full feature size, wall distance, native failed
checks, sampled surface fidelity, measured layers, cell budget and prior interventions.
Distinguish narrow gaps from near-wall snap artifacts; never confuse wall distance with gap.
Distance refinement means metres in the canonical frame. A region's min/max are metres.
No raw dictionary, shell commands, threshold relaxation, surface deletion or layer removal.
Return ONLY a JSON object {hypothesis, counterevidence, expected_change, actions:[...]}.
Use 1..4 actions, each with kind, why, evidence:[existing diagnostic IDs].
Allowed kinds: local_refine (min,max,level), snap_smooth, transition, surface_refine,
layer_smooth, layer_trim. Prefer local interventions grounded in a specific cluster.
surface_refine is GLOBAL and accepts NO min/max/level parameters. local_refine is
the ONLY coordinate-box action. Never duplicate global surface_refine in one proposal.
All other actions accept only kind/why/evidence. Reject unrelated extra fields.
Actual layer_shortfall face centres are stronger evidence for layer repair than generic
allGeometry concavity diagnostics, which alone do not imply an FV quality failure.
If evidence is unavailable, say so in counterevidence; do not invent spatial locations.
Propose a falsifiable explanation and expected measurable improvement. Do not re-propose
an intervention that already failed without a new reason. The harness certifies all actions.
The optional image is a sampled orthographic diagnostic, not a fidelity certificate.'''


def request_advice(run_dir,round_index,evidence,timeout=150):
    spool=Path(run_dir)/'advisor';spool.mkdir(exist_ok=True)
    request=spool/f'request_{round_index}.json';response=spool/f'response_{round_index}.json'
    write_json(request,dict(round=round_index,evidence=evidence,request_id=sha256(Path(run_dir)/'input/body.stl')))
    started=time.monotonic()
    while time.monotonic()-started<timeout:
        if response.exists():
            answer=read_json(response)
            return answer.get('decision'),answer
        time.sleep(1)
    return None,dict(error='advisor unavailable before wait deadline',calls=0)


def serve(run_dir,key_file,base_url='https://api.deepseek.com',model='deepseek-flash',
          max_calls=6,cost_limit=.05,seconds=5400,ledger_path=None):
    run_dir=Path(run_dir);spool=run_dir/'advisor';spool.mkdir(parents=True,exist_ok=True)
    # Credential is read once; never included in request, ledger or exception messages.
    key=Path(key_file).read_text().strip()
    ledger=Path(ledger_path) if ledger_path else run_dir.parent.parent/'evidence/advisor_usage.json'
    ledger.parent.mkdir(parents=True,exist_ok=True)
    @contextmanager
    def locked():
        import fcntl
        with ledger.with_suffix('.lock').open('a') as fh:
            fcntl.flock(fh,fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(fh,fcntl.LOCK_UN)
    usage=read_json(ledger) if ledger.exists() else dict(calls=0,estimated_usd=0.,requests=[],model=model)
    start=time.monotonic()
    while time.monotonic()-start<seconds:
        for req in sorted(spool.glob('request_*.json')):
            response=spool/req.name.replace('request_','response_')
            if response.exists(): continue
            data=read_json(req)
            evidence=json.dumps(data['evidence'],ensure_ascii=False)
            if len(evidence)>24000:
                write_json(response,dict(error='evidence exceeds bounded context'));continue
            # Peak pricing ceiling from official docs, including all output/reasoning tokens.
            max_output=3072;input_ceiling=14000
            reserved=(input_ceiling*.30+max_output*1.20)/1e6
            with locked():
                usage=read_json(ledger) if ledger.exists() else dict(calls=0,estimated_usd=0.,requests=[],model=model)
                if usage['calls']>=max_calls or usage['estimated_usd']+reserved>cost_limit:
                    write_json(response,dict(error='hard global advisor call/cost budget exhausted'));continue
                usage['calls']+=1;usage['estimated_usd']+=reserved
                write_json(ledger,usage)  # Reserve before sending, including failed attempts.
            messages=[dict(role='system',content=SYSTEM),dict(role='user',content=evidence)]
            image_path=run_dir/f'round{data["round"]}/spatial.png'
            if image_path.exists() and image_path.stat().st_size<350000:
                image='data:image/png;base64,'+base64.b64encode(image_path.read_bytes()).decode()
                messages[1]['content']=[dict(type='text',text=evidence),
                     dict(type='image_url',image_url=dict(url=image,detail='low'))]
            payload=dict(model=model,messages=messages,max_tokens=max_output,
                         response_format=dict(type='json_object'),thinking=dict(type='disabled'),temperature=.2)
            started=time.monotonic()
            try:
                request=urllib.request.Request(base_url.rstrip('/')+'/chat/completions',
                    data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',
                    'Authorization':'Bearer '+key})
                with urllib.request.urlopen(request,timeout=110) as http:
                    raw=json.load(http)
                decision=json.loads(raw['choices'][0]['message']['content'])
                tokens=raw.get('usage',{})
                spent=(tokens.get('prompt_tokens',input_ceiling)*.30+
                       tokens.get('completion_tokens',max_output)*1.20)/1e6
                record=dict(round=data['round'],request_sha256=sha256(req),usage=tokens,
                            usd_at_peak_price_ceiling=spent,seconds=time.monotonic()-started,
                            provider_model=raw.get('model'),finish_reason=raw['choices'][0].get('finish_reason'))
                with locked():
                    usage=read_json(ledger)
                    usage['estimated_usd']+=spent-reserved
                    usage['requests'].append(record)
                    write_json(ledger,usage)
                write_json(response,dict(decision=decision,metadata=record))
            except Exception as e:
                # Only exception type, not HTTP request object or headers.
                write_json(response,dict(error=type(e).__name__,seconds=time.monotonic()-started))
                with locked():
                    usage=read_json(ledger)
                    usage['requests'].append(dict(round=data['round'],run=str(run_dir),error=type(e).__name__,reserved_usd=reserved))
                    write_json(ledger,usage)
        if (run_dir/'agent_run.json').exists() and read_json(run_dir/'agent_run.json').get('status') in ('completed','failed','blocked'):
            return usage
        time.sleep(2)
    return usage
