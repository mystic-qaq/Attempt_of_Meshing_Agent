"""Freeze the portfolio experiment before running any new mesh or model call."""
import argparse
import shutil
import urllib.request
from pathlib import Path

import numpy as np
import trimesh

from cfdmesh.io import read_json, write_json, sha256, code_hash

CAR_URL='https://raw.githubusercontent.com/nathanrooy/ahmed-bluff-body-cfd/4b17eba06f9b946de9261a9ae713e38fa1971b72/geometry/ahmed_25deg_m.stl'
CAR_SHA256='c89ec3e3f4d1e51485e1313e456385a8595cf39f0dbd395cd952887fe8b034b7'

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


def canonical_geometries(folder):
    cylinder = trimesh.creation.cylinder(radius=.35, height=1.4, sections=64)
    cylinder.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    cylinder.export(folder / 'finite_cylinder.stl')
    spheroid = trimesh.creation.icosphere(subdivisions=4, radius=1)
    spheroid.vertices *= np.array([1.5, .35, .35])
    spheroid.export(folder / 'submerged_spheroid.stl')
    x = (1 - np.cos(np.linspace(0, np.pi, 81))) / 2
    t = 5 * .12 * (.2969 * np.sqrt(x) - .126 * x - .3516 * x*x + .2843 * x**3 - .1036 * x**4)
    outline = np.column_stack([np.r_[x, x[-2:0:-1]], np.r_[t, -t[-2:0:-1]]])
    vertices = np.array([[a, y, b] for y in [-1., 1.] for a, b in outline])
    n = len(outline); faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.extend([[i, j, n+j], [i, n+j, n+i]])
    for side, y in [(0, -1.), (n, 1.)]:
        centre = len(vertices); vertices = np.vstack([vertices, [.5, y, 0.]])
        for i in range(n):
            faces.append([centre, side+i, side+(i+1) % n])
    wing = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    wing.fix_normals()
    wing.apply_transform(trimesh.transformations.rotation_matrix(-5*np.pi/180, [0, 1, 0]))
    wing.export(folder / 'finite_wing.stl')


def setup(root, history=None, geometry_dir=None):
    root = Path(root).resolve()
    if (root / 'portfolio_protocol.json').exists():
        raise FileExistsError('protocol already frozen; choose a new experiment directory')
    geo = root / 'geometry'; geo.mkdir(parents=True, exist_ok=True)
    (root / 'runs').mkdir(exist_ok=True)
    if history:
        history = Path(history).resolve()
        for name in ['ahmed_public_25', 'finite_wing', 'finite_cylinder', 'submerged_spheroid']:
            shutil.copyfile(history / 'geometry' / (name + '.stl'), geo / (name + '.stl'))
    else:
        canonical_geometries(geo)
        car = geo / 'ahmed_public_25.stl'
        if geometry_dir:
            shutil.copyfile(Path(geometry_dir) / car.name, car)
        else:
            with urllib.request.urlopen(CAR_URL, timeout=120) as response:
                data = response.read(20_000_001)
            if len(data) > 20_000_000:
                raise ValueError('source download exceeds size ceiling')
            car.write_bytes(data)
        if sha256(car)!=CAR_SHA256:raise ValueError('vehicle source differs from the pinned benchmark geometry')
    cases = []
    for name, family in [('ahmed_public_25', 'vehicle'), ('finite_wing', 'finite_wing'),
                         ('finite_cylinder', 'bluff_body'), ('submerged_spheroid', 'submerged_body')]:
        context = dict(family=family, objective='external-flow forces and downstream wake resolution',
                       boundary_environment='unbounded_single_phase', flow_direction=[1, 0, 0], up_direction=[0, 0, 1])
        if family == 'finite_wing': context['span_direction'] = [0, 1, 0]
        parent = None
        if history:
            context = read_json(history / 'contexts' / (name + '.json'))
            if name in ('ahmed_public_25', 'submerged_spheroid'):
                parent = history / 'runs' / ('model_' + name)
        context_path = root / 'contexts' / (name + '.json'); write_json(context_path, context)
        prior_attempts = 0
        if parent:
            old = read_json(parent / 'agent_run.json')
            prior_attempts = len(old['rounds']) + old.get('prior_mesh_attempts', 0)
            if old['source_sha256'] != sha256(geo / (name + '.stl')): raise ValueError('history source mismatch')
        cases.append(dict(id=name, family=family, source=str(geo / (name + '.stl')),
                          source_sha256=sha256(geo / (name + '.stl')), scenario_file=str(context_path),
                          parent=str(parent) if parent else None, prior_mesh_attempts=prior_attempts,
                          new_mesh_attempt_limit=5-prior_attempts,
                          split='development_continuation' if parent else 'new_closed_loop_on_previously_used_shape',
                          source_kind='public_simplified_vehicle' if family == 'vehicle' else 'synthetic_canonical_probe',
                          source_url=CAR_URL if family == 'vehicle' else None))
    protocol = dict(schema_version=1, code_sha256=code_hash(), cases=cases,
        comparator='same episode first native mesh, with the same science context and initial model; stop there for the one-shot baseline',
        control_note='No second baseline job: its Dict and mesh are exactly the recorded first attempt, before native feedback. Feedback costs more attempts; report that cost.',
        cell_cap=2_000_000, total_attempt_cap_including_history=5, source_api_usd_cap=.5,
        initial_model=True, require_layers=True, flow_probe=True,
        per_round_seconds=600, new_episode_seconds=3600, mpi_processes=16,
        advisor=dict(max_turns=4, max_output=12288, reasoning_effort='high', max_calls=24),
        frozen_selection='Among original and new attempts with native quality, geometry, budget and scene gates passing, choose highest actual >=5-layer area coverage; tie: fewer cells. If none qualify, select no mesh.',
        metrics=['native_quality', 'sampled_geometry_fidelity', 'actual_layer_area_coverage', 'native_scene_resolution', 'cells', 'wall_seconds', 'api_cost_upper_bound', 'decision_origin', 'joint_acceptance', 'short_flow_probe'],
        claim_policy='A layer improvement is partial progress only if quality/fidelity/scene stay valid. LLM and deterministic fallback contributions are separate. All attempts are retained. No success-rate or held-out industrial generalisation claim.',
        scope='Unbounded single-phase +X flow/+Z up. No road ground, free surface, production-car/aircraft qualification, converged force accuracy, or mesh-independence proof.')
    write_json(root / 'portfolio_protocol.json', protocol)
    sync_budget_scope(root, history)
    print('Frozen', len(cases), 'cases; code', protocol['code_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root'); parser.add_argument('--history-root'); parser.add_argument('--geometry-dir')
    parser.add_argument('--sync-budget-only',action='store_true')
    args = parser.parse_args()
    if args.sync_budget_only:sync_budget_scope(args.root,args.history_root)
    else:setup(args.root, args.history_root, args.geometry_dir)
