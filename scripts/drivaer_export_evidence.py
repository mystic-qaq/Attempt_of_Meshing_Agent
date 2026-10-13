"""Export reviewable native evidence, omitting geometry, grids, keys and private reasoning."""
import argparse
import json
from pathlib import Path
from cfdmesh.io import read_json,write_json,sha256


PRIVATE={'credential_fingerprint','reasoning_content','reasoning_sha256'}


def public_value(value,base):
    if isinstance(value,dict):return {k:public_value(v,base) for k,v in value.items() if k not in PRIVATE}
    if isinstance(value,list):return [public_value(v,base) for v in value]
    if isinstance(value,str):
        import re
        return re.sub(r'/gpfs/share/home/[0-9]+','<REMOTE_HOME>',value.replace(str(base),'<REMOTE_WORKSPACE>'))
    return value


def export(base,out):
    if out.exists():raise FileExistsError('evidence exports are immutable; choose a fresh directory')
    roots=sorted(p for p in base.iterdir() if p.is_dir() and (p.name.startswith('campaign') or p.name.startswith('program_one_shot')))
    for root in roots:
        states=list((root/'runs').glob('*/agent_run.json')) if (root/'runs').exists() else list(root.glob('agent_run.json'))
        if any(read_json(p)['status']=='running' for p in states):raise ValueError('export requires completed episodes')
    out.mkdir();manifest=[]
    for root in roots:
        files=list(root.glob('protocol.json'))+list(root.glob('api_budget_scope.json'))+list(root.glob('launch.json'))
        runs=sorted((root/'runs').iterdir()) if (root/'runs').exists() else [root]
        for run in runs:
            if not (run/'agent_run.json').exists():continue
            files += [run/n for n in ('agent_run.json','manifest.json','input_contract.json','initial_spec.json','scenario_contract.json','preflight.json') if (run/n).exists()]
            files += list((run/'advisor').glob('*.json'))
            for case in sorted(run.glob('round*')):
                if not case.is_dir():continue
                files += [case/n for n in ('record.json','round.json','native_trace_summary.json') if (case/n).exists()]
                files += [case/'system'/n for n in ('snappyHexMeshDict','meshQualityDict','blockMeshDict','surfaceFeatureExtractDict','fvSolution','fvSchemes') if (case/'system'/n).exists()]
                files += list((case/'logs').glob('*.log'))
                # These large measured artifacts stay remote; hashes bind the diagnostics.
                native_files=list((case/'constant/polyMesh').glob('*'))+list(case.glob('*/nSurfaceLayers'))+list(case.glob('*/thickness'))+list(case.glob('body.obj'))
                write_json(out/case.relative_to(base)/'native_artifact_hashes.json',
                    {str(p.relative_to(case)):sha256(p) for p in native_files if p.is_file()})
        for path in sorted(set(files)):
            target=out/path.relative_to(base);target.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix=='.json':write_json(target,public_value(read_json(path),base))
            else:target.write_text(public_value(path.read_text(errors='replace'),base),encoding='utf-8')
            manifest.append(dict(path=str(path.relative_to(base)),original_sha256=sha256(path),export_sha256=sha256(target),
                transformed=True,transformation='remote paths replaced; credential and private-reasoning fields omitted'))
    write_json(out/'manifest.json',dict(files=manifest,hidden_reasoning_exported=False,mesh_files_included=False,
        interpretation='sanitized review evidence; original hashes refer to immutable remote files; transformed export hashes are separate'))
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base');p.add_argument('output');a=p.parse_args()
    print('public files',len(export(Path(a.base).resolve(),Path(a.output).resolve())))
