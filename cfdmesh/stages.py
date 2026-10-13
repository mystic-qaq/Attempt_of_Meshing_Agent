"""Hash-bound, copied stage anchors. A snap anchor is not a CFD certificate."""
import copy
import hashlib
import json
import shutil
from pathlib import Path
from .io import sha256, read_json, write_json

CORE = ('points', 'faces', 'owner', 'neighbour', 'boundary')


def snap_signature(spec):
    data = copy.deepcopy(spec.to_dict() if hasattr(spec, 'to_dict') else spec)
    data.pop('layers', None)
    for region in data.get('regions', []):
        region.pop('why', None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def mesh_hashes(case):
    mesh = Path(case) / 'constant/polyMesh'
    return {name: sha256(mesh / name) for name in CORE}


def register_snap(case, spec, geometry, evidence, budget):
    q = evidence.get('quality') or {}
    f = evidence.get('fidelity') or {}
    scene = evidence.get('scenario_screen')
    if not (evidence.get('accepted') and q.get('accepted') and f.get('accepted')
            and (scene is None or scene.get('accepted'))):
        raise ValueError('snap anchor requires independently accepted quality, fidelity and scene')
    record = dict(stage='snap', eligible=True, case=str(Path(case).resolve()),
                  geometry_sha256=sha256(geometry), snap_signature=snap_signature(spec),
                  poly_mesh_sha256=mesh_hashes(case), cells=q['metrics']['cells'], budget=budget,
                  evidence_grade='snap only; layers and physical accuracy unverified')
    write_json(Path(case) / 'snap_anchor.json', record)
    return record


def copy_snap(anchor, destination, spec, geometry, budget):
    source = Path(anchor['case'])
    receipt = read_json(source / 'snap_anchor.json')
    if receipt != anchor or not receipt.get('eligible') or receipt.get('stage') != 'snap':
        raise ValueError('unverified snap anchor receipt')
    if receipt['snap_signature'] != snap_signature(spec):
        raise ValueError('snap-relevant controls changed; a new snap stage is required')
    if receipt['geometry_sha256'] != sha256(geometry) or receipt['budget'] != budget:
        raise ValueError('snap geometry or budget mismatch')
    if mesh_hashes(source) != receipt['poly_mesh_sha256']:
        raise ValueError('snap anchor files mutated')
    destination = Path(destination)
    shutil.copytree(source / 'constant/polyMesh', destination / 'constant/polyMesh')
    for feature in (source / 'constant/triSurface').glob('*.eMesh'):
        shutil.copy2(feature, destination / 'constant/triSurface' / feature.name)
    if mesh_hashes(destination) != receipt['poly_mesh_sha256']:
        raise ValueError('copied snap hash mismatch')
    return dict(source=str(source), source_hashes_before=receipt['poly_mesh_sha256'],
                copied_hashes=mesh_hashes(destination), copy_policy='regular files; no links')


def verify_snap_unchanged(anchor):
    after = mesh_hashes(anchor['case'])
    if after != anchor['poly_mesh_sha256']:
        raise ValueError('snap anchor changed during trial')
    return dict(source_mutated=False, source_hashes_after=after)
