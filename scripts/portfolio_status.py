"""Small, credential-free status snapshot for ongoing portfolio jobs."""
import json
import sys
from pathlib import Path
from cfdmesh.io import read_json

root = Path(sys.argv[1])
for path in sorted((root / 'runs').iterdir()):
    state = path / 'agent_run.json'; ledger = path / 'advisor/usage.json'
    if not state.exists(): continue
    run = read_json(state); usage = read_json(ledger) if ledger.exists() else {}
    summary = dict(case=path.name, status=run['status'], stop=run.get('stop_reason'),
        attempts=[dict(index=r['round'], origin=r['decision']['source'],
                       cells=(r['evidence'].get('quality') or {}).get('metrics', {}).get('cells'),
                       coverage=r['evidence']['layers'].get('coverage'),
                       reasons=r['evidence']['reasons']) for r in run['rounds']],
        calls=usage.get('calls', 0), usd=usage.get('estimated_usd', 0),
        initial_rejection=run.get('initial_decision', {}).get('rejected_advisor'))
    print(json.dumps(summary, ensure_ascii=False))
