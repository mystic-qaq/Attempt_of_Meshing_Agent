"""Keep same-source expenses visible across related experiment roots."""
from pathlib import Path
from .io import read_json, write_json


def sync_budget_scope(root, history=None):
    root=Path(root).resolve(); roots=[str(root/'runs')]; locks=root/'api_case_locks'
    aliases={};provenance={};records=[]
    for parent in [root]+([Path(history)] if history else []):
        if (parent/'api_budget_scope.json').exists():records.append(read_json(parent/'api_budget_scope.json'))
    for previous in records:
        roots=list(dict.fromkeys(previous['run_roots']+roots));locks=Path(previous['lock_directory'])
        for key,value in previous.get('source_aliases',{}).items():
            if key in aliases and aliases[key]!=value:raise ValueError('conflicting budget source alias')
            aliases[key]=value
        provenance.update(previous.get('source_alias_provenance',{}))
    write_json(root/'api_budget_scope.json',dict(run_roots=roots,lock_directory=str(locks),source_aliases=aliases,source_alias_provenance=provenance))
    # Older coordinators must see expenses in the new root too, under the same lock.
    for run_root in roots:
        target=Path(run_root).parent/'api_budget_scope.json'
        if target.exists() and target!=root/'api_budget_scope.json':
            config=read_json(target)
            config['run_roots']=list(dict.fromkeys(config['run_roots']+[str(root/'runs')]))
            existing=config.get('source_aliases',{})
            if any(k in existing and existing[k]!=v for k,v in aliases.items()):raise ValueError('conflicting older budget source alias')
            config['source_aliases']={**existing,**aliases}
            config['source_alias_provenance']={**config.get('source_alias_provenance',{}),**provenance}
            write_json(target,config)
