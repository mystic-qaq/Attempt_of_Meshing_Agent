"""Curate a GitHub-ready tree; refuse credentials, private paths and source meshes."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def export(source, destination, update=False):
    source=Path(source).resolve(); destination=Path(destination).resolve()
    previous=None
    if destination.exists():
        if not update or not (destination/'PUBLICATION_MANIFEST.json').is_file():raise FileExistsError('export destination must be fresh or a verified managed export')
        previous=json.loads((destination/'PUBLICATION_MANIFEST.json').read_text(encoding='utf-8'))
        expected={f['path'] for f in previous['files']}|{'PUBLICATION_MANIFEST.json'}
        actual={p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file() and '.git' not in p.relative_to(destination).parts}
        if actual!=expected or any(hashlib.sha256((destination/f['path']).read_bytes()).hexdigest()!=f['sha256'] for f in previous['files']):raise ValueError('managed export has user edits or extra files; update refused')
    files=[]
    for name in ['README.md','NOTICE.md','LICENSE','pyproject.toml','.gitignore','.gitattributes','requirements-v4.txt']:
        files.append(source/name)
    if (source/'README.zh-CN.md').is_file():files.append(source/'README.zh-CN.md')
    for folder in ['cfdmesh','tests','docs','assets','benchmarks','.github','native_tools']:
        files.extend(p for p in (source/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files.extend((source/'scripts').glob('*.py'))
    files.extend((source/'scripts').glob('*.sh'))
    files.append(source/'scripts/export_portfolio.py')
    files.append(source/'scripts/native_gap_smoke.py')
    files.append(source/'scripts/measure_gap_smoke.py')
    files.append(source/'scripts/drivaer_visualize.py')
    files.extend(p for p in (source/'results/drivaer_20261011').rglob('*') if p.is_file())
    files.extend(p for p in (source/'results/mechanisms_20261012').rglob('*') if p.is_file())
    files.extend(p for p in (source/'results/drivaer_v9_20261012').rglob('*') if p.is_file())
    files.extend(p for p in (source/'results/drivaer_focus_20261012').rglob('*') if p.is_file())
    files.extend(p for p in (source/'results/publication_20261013').rglob('*') if p.is_file())
    files=list(dict.fromkeys(files))
    if previous and {f['path'] for f in previous['files']}-{p.relative_to(source).as_posix() for p in files}:raise ValueError('new allowlist drops old files; use a fresh destination')
    secrets=re.compile(rb'sk-[A-Za-z0-9_-]{16,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----')
    private=re.compile(rb'/gpfs/share/home/[0-9]+|[A-Z]:[/\\]Users[/\\][^/\\\s]+')
    manifest=[]
    # Audit the entire allowlist before writing anything.
    for path in files:
        data=path.read_bytes()
        if path.suffix.lower() in ('.key','.stl','.step','.stp','.obj','.foam'):
            raise ValueError('prohibited publication artifact: '+str(path.relative_to(source)))
        if path.suffix.lower() not in ('.png','.jpg','.pdf') and (secrets.search(data) or private.search(data)):
            raise ValueError('secret/private-path scan failed: '+str(path.relative_to(source)))
        manifest.append(dict(path=path.relative_to(source).as_posix(),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
    destination.mkdir(parents=True,exist_ok=update)
    for path in files:
        target=destination/path.relative_to(source); target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,target)
    (destination/'PUBLICATION_MANIFEST.json').write_text(json.dumps(dict(files=manifest,
        exclusions=['secrets','source geometry','full native meshes','provider reasoning','private account paths','historical raw reports'],
        validation='allowlist and credential/private-path scan passed'),indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Audited publication files:',len(files))


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('source'); p.add_argument('destination');p.add_argument('--update',action='store_true')
    args=p.parse_args(); export(args.source,args.destination,args.update)
