"""Trusted measured plan anchors. Candidate is never a production certificate."""
import copy,hashlib,json

def plan_signature(spec):
    data=copy.deepcopy(spec.to_dict() if hasattr(spec,'to_dict') else spec)
    for region in data.get('regions',[]):region.pop('why',None)
    return json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False)

def plan_id(spec):
    return 'plan:'+hashlib.sha256(plan_signature(spec).encode()).hexdigest()[:16]

def eligible(record,budget):
    e=record.get('evidence') or {};q=e.get('quality') or {};f=e.get('fidelity') or {}
    cells=q.get('metrics',{}).get('cells')
    return bool(q.get('verified') and q.get('accepted') and f.get('accepted')
                and not record.get('native',{}).get('error') and cells is not None and 0<cells<=budget)

def catalog(records,budget):
    items={}
    for r in records:
        e=r.get('evidence') or {};q=e.get('quality') or {};key=plan_id(r['spec'])
        items[key]=dict(plan_id=key,round=r['round'],eligible_for_restore=eligible(r,budget),
                       case=r.get('native',{}).get('case'),
                       spec=copy.deepcopy(r['spec']),quality=q,layer_coverage=e.get('layers',{}).get('coverage'),
                       fidelity_accepted=e.get('fidelity',{}).get('accepted',False),reasons=e.get('reasons',['measured native evidence unavailable']),
                       grade='provisional: still requires complete layers and sane flow; no industrial accuracy certificate')
    return list(items.values())

def best_candidate(items):
    valid=[x for x in items if x['eligible_for_restore']]
    return max(valid,key=lambda x:(x['layer_coverage'] or 0,-x['quality']['metrics']['cells'])) if valid else None

def compact_catalog(items):
    return [{**{k:v for k,v in x.items() if k not in ('spec','quality')},
             'metrics':x['quality'].get('metrics',{}),
             'layer_parameters':copy.deepcopy(x['spec']['layers']),
             'surface_level':x['spec']['surface']['level_max'],
             'region_names':[r['name'] for r in x['spec']['regions']]} for x in items]
