"""Compile measured cluster IDs to exact boxes, avoiding LLM coordinate transcription."""
import copy
import numpy as np


def resolve_cluster_actions(actions, spatial, finest):
    lookup={d['id']:d for d in spatial or []};result=[];targets=set()
    for action in actions:
        if 'compiled_measured_target' in action:raise ValueError('measured-target provenance is assigned only by the compiler')
        if action.get('kind')!='cluster_refine':result.append(copy.deepcopy(action));continue
        if set(action)-{'kind','ids','level','padding_cells','why','evidence'}:
            raise ValueError('unknown cluster refinement fields')
        ids=action.get('ids');padding=action.get('padding_cells',0)
        if not isinstance(ids,list) or not 1<=len(ids)<=4 or len(set(ids))!=len(ids):
            raise ValueError('cluster_refine requires 1..4 unique measured IDs')
        if isinstance(padding,bool) or not isinstance(padding,(int,float)) or not np.isfinite(padding) or not 0<=padding<=2:
            raise ValueError('padding_cells must be 0..2 nominal cells')
        for target in ids:
            if target not in lookup:raise ValueError('unknown measured cluster '+str(target))
            if target not in action.get('evidence',[]):raise ValueError('cluster target must also be cited as evidence')
            item=lookup[target];margin=float(padding)*finest
            result.append(dict(kind='local_refine',min=(np.array(item['min'])-margin).tolist(),
                max=(np.array(item['max'])+margin).tolist(),level=action['level'],why=action['why'],evidence=[target],compiled_measured_target=target))
            targets.add(target)
    if len(targets)>4:raise ValueError('at most four measured cluster targets per proposal')
    return result
