"""Resume paid Flash measurements in the same source/spec, without replaying hidden thought."""
from pathlib import Path
from .io import read_json,sha256


def visible_queries(root,source_sha256,spec,centred_sha256):
    root=Path(root);data=read_json(root/'agent_run.json');request=read_json(root/'advisor/request_-1.json')
    if data['status']=='running' or data['source_sha256']!=source_sha256 or data.get('source_mutated'):
        raise ValueError('decision checkpoint requires a terminal immutable same-source episode')
    if data.get('profile',{}).get('model')!='deepseek-flash' or data['rounds']:
        raise ValueError('checkpoint must be an uncommitted Flash decision with no executed native trial')
    if request['request_id']!=centred_sha256 or request['evidence']['current_spec']!=spec.to_dict():
        raise ValueError('checkpoint geometry or executable base changed')
    inherited=request['evidence'].get('resume_visible_queries') or {}
    messages=list(inherited.get('messages',[]));proof=list(inherited.get('proof',[]));unavailable=list(inherited.get('unavailable_calls',[]))
    for path in sorted((root/'advisor').glob('public_answer_-1_*.json')):
        answer=read_json(path);calls=answer.get('tool_calls') or []
        if not calls:continue
        if len(calls)==1 and calls[0]['function']['name']=='propose_mesh_plan':
            turn=path.stem.rsplit('_',1)[-1];reply=root/'advisor'/f'tool_response_-1_{turn}_final.json'
            if reply.exists():
                import json
                result=read_json(reply)
                messages.append(dict(role='assistant',content=answer.get('content') or '',tool_calls=calls))
                messages.append(dict(role='tool',tool_call_id=calls[0]['id'],content=json.dumps(dict(
                    status='previous proposal not executed; correct its computed rejection before a new native trial',compute_preview=result))))
                proof.append(dict(public_answer_sha256=sha256(path),final_preview_sha256=sha256(reply)))
            continue
        if any(c['function']['name']=='propose_mesh_plan' for c in calls):continue
        turn=path.stem.rsplit('_',1)[-1];responses=[];complete_calls=[]
        for i,call in enumerate(calls):
            query=root/'advisor'/f'tool_request_-1_{turn}_{i}.json';result=query.with_name(query.name.replace('tool_request_','tool_response_'))
            if not query.exists() or not result.exists():
                unavailable.append(dict(tool_call_id=call['id'],tool=call['function']['name'],
                    status='no complete computed receipt; not a measurement; original call remains in parent archive'))
                continue
            import json
            q=read_json(query)
            if q['name']!=call['function']['name'] or q['arguments']!=json.loads(call['function']['arguments']):
                raise ValueError('visible query and computed receipt differ')
            responses.append(dict(role='tool',tool_call_id=call['id'],content=json.dumps(read_json(result))))
            complete_calls.append(call)
            proof.append(dict(query_sha256=sha256(query),result_sha256=sha256(result)))
        if complete_calls:
            messages.append(dict(role='assistant',content=answer.get('content') or '',tool_calls=complete_calls));messages.extend(responses)
    if not messages:raise ValueError('no measured visible queries to resume')
    return dict(messages=messages,proof=proof,unavailable_calls=unavailable,source_sha256=source_sha256,
        interpretation='same-source paid measurements reused; final compute preview and new native validation still mandatory; no hidden reasoning')
