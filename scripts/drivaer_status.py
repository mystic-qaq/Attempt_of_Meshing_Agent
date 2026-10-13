"""Compact status, including real decision attribution and shared-source API spend."""
import argparse
from pathlib import Path
from cfdmesh.io import read_json
from cfdmesh.scientific_advisor import geometry_spend

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('experiment');a=p.parse_args();root=Path(a.experiment)
    for run in sorted((root/'runs').iterdir()):
        if not (run/'agent_run.json').exists():print(run.name,'not started');continue
        data=read_json(run/'agent_run.json');_,total,_=geometry_spend(run)
        rows=data['rounds'];last=rows[-1] if rows else {};q=(last.get('evidence',{}).get('quality') or {})
        active=[(p.parent.name,read_json(p).get('stage')) for p in run.glob('round*/round.json') if read_json(p).get('status')=='running']
        print(run.name,data['status'],'stages',len(rows),'active',active,'last',last.get('stage'),
            'failed',q.get('n_failed'),'coverage',last.get('evidence',{}).get('layers',{}).get('coverage'),
            'model_trials',sum(r['decision']['source']=='model' for r in rows),
            'shared_usd_ceiling',round(total,5),'stop',data.get('stop_reason'))
