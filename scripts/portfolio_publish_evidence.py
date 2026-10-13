"""Collect compact, path-redacted measured evidence; never copy geometry or private reasoning."""
import argparse
import re
from pathlib import Path
from cfdmesh.io import read_json, write_json, sha256


def scrub(text):
    text=re.sub(r'/gpfs/share/home/\d+/cfd_meshing_agent', '<PRIVATE_PROJECT_ROOT>', text)
    return re.sub(r'/gpfs/share/home/\d+', '<PRIVATE_HOME>', text)


def publish(root, measured, destination):
    root=Path(root); measured=Path(measured); destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    report=read_json(measured/'results.json'); manifest=[]
    def copy_redacted(source, relative):
        source=Path(source); target=destination/relative; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(scrub(source.read_text(encoding='utf-8',errors='replace')),encoding='utf-8')
        manifest.append(dict(path=relative,source_sha256=sha256(source),published_sha256=sha256(target),
                             path_redacted=True,measurement_values_modified=False))
    copy_redacted(root/'portfolio_protocol.json','protocol.json')
    copy_redacted(measured/'results.json','results.json')
    for c in report['cases']:
        for a in c['attempts']:
            folder=Path(a['case']); prefix=f"attempts/{c['id']}/attempt_{a['attempt']}"
            for relative in ['record.json','round.json','system/snappyHexMeshDict','system/blockMeshDict',
                             'system/meshQualityDict','logs/checkMesh.log','logs/checkMeshExtended.log','logs/nativeBoundaryCheck.log']:
                source=folder/relative
                if source.exists(): copy_redacted(source,prefix+'/'+relative)
        state=root/'runs'/c['id']
        for relative in ['handoff.json','agent_run.json','advisor/usage.json']:
            if (state/relative).exists(): copy_redacted(state/relative,f"episodes/{c['id']}/"+relative)
    extra=root/'proposal_validation_result.json'
    if extra.exists():
        copy_redacted(extra,'separate_proposal_validation/result.json')
        copy_redacted(root/'proposal_validation_protocol.json','separate_proposal_validation/protocol.json')
        for r in read_json(extra)['result']['rounds']:
            folder=Path(r['native']['case'])
            for relative in ['record.json','round.json','system/snappyHexMeshDict','system/blockMeshDict','logs/checkMesh.log']:
                if (folder/relative).exists(): copy_redacted(folder/relative,'separate_proposal_validation/'+relative)
    follow=root/'proposal_followup_result.json'
    if follow.exists():
        copy_redacted(follow,'separate_proposal_followup/result.json')
        copy_redacted(root/'proposal_followup_protocol.json','separate_proposal_followup/protocol.json')
        if (measured/'separate_results.json').exists(): copy_redacted(measured/'separate_results.json','separate_results.json')
        for r in read_json(follow)['rounds']:
            folder=Path(r['native']['case']);prefix=f"separate_proposal_followup/round{r['round']}"
            for relative in ['record.json','round.json','system/snappyHexMeshDict','logs/checkMesh.log']:
                if (folder/relative).exists(): copy_redacted(folder/relative,prefix+'/'+relative)
    write_json(destination/'EVIDENCE_MANIFEST.json',dict(files=manifest,
        exclusions=['STL/CAD','polyMesh','body.obj','provider reasoning','API key'],
        note='Published text has private project paths replaced. Original hashes retained; measurements and parameter values are unchanged.'))
    print('Published evidence files:',len(manifest))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('measured');p.add_argument('destination')
    args=p.parse_args();publish(args.root,args.measured,args.destination)
