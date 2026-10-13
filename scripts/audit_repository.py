"""Check the DrivAer publication boundary, local links, and retained measurements."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT_FILES={'.gitattributes','.gitignore','LICENSE','NOTICE.md','README.md','README.zh-CN.md','pyproject.toml','requirements-native.txt'}
DOCS={'ARCHITECTURE.md','PROTOCOL.md','RUNNING.md','FINDINGS.zh-CN.md'}
FOLDERS={'cfdmesh','tests','scripts','native_tools','.github','docs','results'}
SECRET=re.compile(rb'sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----')
PRIVATE_PATH=re.compile(rb'/gpfs/share/home/[0-9]+|[A-Z]:[/\\]Users[/\\][^/\\\s]+')
LEGACY_RELEASE=re.compile(r'\b[vV](?:[1-9]|1[0-4])\b|\b0\.10\.[0-9]+\b')
PROHIBITED={'.stl','.step','.stp','.obj','.foam','.key','.env','.zip','.gz','.bundle'}


def audit(root):
    root=Path(root).resolve();problems=[];count=0
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if any(part in ('.git','__pycache__','.venv','build','dist') or part.endswith('.egg-info') for part in relative.parts):
            continue
        if not path.is_file():continue
        count+=1
        name=relative.as_posix()
        if path.is_symlink():problems.append(name+': symlink outside publication contract')
        if len(relative.parts)==1 and path.name not in ROOT_FILES:
            problems.append(name+': unexpected root file')
        elif len(relative.parts)>1 and relative.parts[0] not in FOLDERS:
            problems.append(name+': legacy or unapproved directory')
        if relative.parts[0]=='docs' and (len(relative.parts)!=2 or path.name not in DOCS):
            problems.append(name+': local-only or obsolete document')
        if relative.parts[0]=='results' and relative.parts[:2]!=('results','drivaer'):
            problems.append(name+': experiment outside the DrivAer study')
        if path.suffix.lower() in PROHIBITED or path.name.startswith('.env') or path.name.startswith('portfolio_'):
            problems.append(name+': prohibited artifact')
        data=path.read_bytes()
        if path.suffix.lower() in ('.png','.jpg','.jpeg'):continue
        if SECRET.search(data) or PRIVATE_PATH.search(data):
            problems.append(name+': credential/private-path scan failed')
        if path.suffix=='.json':
            try:json.loads(data)
            except (ValueError,UnicodeError):problems.append(name+': invalid JSON')
        if path.suffix=='.md':
            text=data.decode('utf-8')
            if LEGACY_RELEASE.search(text):problems.append(name+': obsolete release label')
            for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',text):
                target=target.strip().split(' "',1)[0].strip('<>')
                if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',target) or target.startswith('#'):continue
                destination=(path.parent/target.split('#',1)[0]).resolve()
                if not destination.is_relative_to(root) or not destination.is_file():
                    problems.append(name+': broken local link '+target)
    evidence=root/'results/drivaer/evidence.json'
    manifest=root/'results/drivaer/manifest.json'
    if not evidence.is_file() or not manifest.is_file():
        problems.append('missing complete DrivAer evidence/manifest')
    else:
        records=json.loads(evidence.read_text(encoding='utf-8'))
        attempts=[a for run in records['runs'] for a in run['attempts']]
        if len(attempts)!=records['campaign_native_attempts']:
            problems.append('native stage count does not match complete records')
        if sum(a['research_eligible'] for a in attempts)!=records['eligible_native_campaign_attempts']:
            problems.append('eligible native stage count does not match complete records')
        for entry in json.loads(manifest.read_text(encoding='utf-8'))['files']:
            target=(manifest.parent/entry['path']).resolve()
            if not target.is_relative_to(manifest.parent) or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=entry['sha256']:
                problems.append('evidence hash mismatch: '+entry['path'])
    if problems:raise ValueError('\n'.join(problems))
    return count


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',nargs='?',default=str(Path(__file__).resolve().parents[1]))
    print('Audited files:',audit(parser.parse_args().root))
