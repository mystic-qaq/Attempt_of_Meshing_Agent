"""Unpaid real-case query/target replay; preserves all native mesh files."""
import argparse
from pathlib import Path
import numpy as np
import trimesh
from cfdmesh.geometry import Geometry
from cfdmesh.case_builder import MeshSpec
from cfdmesh.io import read_json,write_json,sha256,code_hash
from cfdmesh.stages import mesh_hashes
from cfdmesh.drivaer import add_observer_target
from cfdmesh.scientific_tools import execute_query

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('out');a=p.parse_args();root=Path(a.run);out=Path(a.out)
    if out.exists():raise FileExistsError('replay output is immutable')
    audit=read_json(root/'input/audit.json');probe=np.load(root/'input/probe.npz')
    m=trimesh.load(root/'input/body.stl',force='mesh',process=False);m.merge_vertices(digits_vertex=12)
    g=Geometry(m,str(root/'input/body.stl'),audit['source_sha256'],sha256(root/'input/body.stl'),
        probe['points'],probe['normals'],probe['inward'],probe['outward'],audit)
    run=read_json(root/'agent_run.json');record=read_json(root/'round0/record.json');spec=MeshSpec.from_dict(record['spec'])
    add_observer_target(record['evidence'],record['native'],spec,g)
    case=Path(record['native']['case']);before=mesh_hashes(case)
    context=dict(geometry=g,spec=spec,evidence=record['evidence'],case=case,budget=12_000_000,
        physics=run['flow'],scenario=run['scenario'],plan_history=run['rounds'],mesh_stage='snap')
    target=next(d for d in record['evidence']['spatial'] if d['id']=='boundary_observer:0')
    region=execute_query('inspect_cluster',{'id':target['id']},context)
    action=dict(kind='cluster_refine',ids=[target['id']],level=6,padding_cells=0,
                why='unpaid measured target compilation replay',evidence=[target['id']])
    preview=execute_query('preview_actions',{'actions':[action]},context)
    after=mesh_hashes(case)
    if after!=before:raise ValueError('native evidence changed during replay')
    write_json(out,dict(code_sha256=code_hash(),region=region,preview=preview,mesh_sha256_before=before,
        mesh_sha256_after=after,source_mutated=False,native_mesh_attempts=0,paid_model_calls=0))
    print('real query samples',region['local']['geometry_samples'],'layer available',region['local']['actual_layers']['available'],
          'compiled target certified',preview['certification']['ok'],flush=True)
