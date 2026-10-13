"""Stock native integration test, not a real-engineering Agent benchmark."""
import argparse
import re
from pathlib import Path
import numpy as np
import trimesh
from cfdmesh.boundary import ear_triangles
from cfdmesh.geometry import prepare
from cfdmesh.case_builder import MeshSpec,DistanceLevel
from cfdmesh.planning import apply_actions
from cfdmesh.runner import run_round
from cfdmesh.io import write_json,sha256,code_hash


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--of-root',required=True);parser.add_argument('--n-procs',type=int,default=8);a=parser.parse_args()
    root=Path(a.directory)
    if root.exists():raise FileExistsError('native smoke output must be fresh')
    root.mkdir(parents=True)
    q=np.array([[-.5,-.3],[.5,-.3],[.5,.3],[.03,.3],[.03,-.15],[-.03,-.15],[-.03,.3],[-.5,.3]])
    vertices=np.vstack([np.column_stack([q,np.full(len(q),z)]) for z in (-.15,.15)])
    triangles=ear_triangles(q);n=len(q);faces=[t[::-1] for t in triangles]+[[i+n for i in t] for t in triangles]
    for i in range(n):
        j=(i+1)%n;faces.extend([[i,j,j+n],[i,j+n,i+n]])
    body=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    if not body.is_watertight or not body.is_winding_consistent:raise ValueError('smoke fixture must be one oriented closed body')
    source=root/'source.stl';body.export(source);g=prepare(source,root/'input',n=1024)
    before=sha256(source);s=MeshSpec();s.domain.base_cells=8
    s.domain.padding_up=s.domain.padding_down=s.domain.padding_side=s.domain.padding_upstream=1;s.domain.padding_downstream=2
    s.surface.level_min=s.surface.level_max=3;s.features.level=3;s.allow_free_standing_zone_faces=False
    s.layers.enabled=False;s.max_global_cells=1_000_000;s.distance_levels=[DistanceLevel(.03125,3),DistanceLevel(.09375,2)]
    action=dict(kind='gap_refine',min=[-.12,-.19,-.2],max=[.12,.32,.2],minimum_cells=6,start_level=3,max_level=4,why='bounded native gap detection in anonymous notch',evidence=['geometry'])
    candidate=apply_actions(s,[action],g,1_000_000);records=[]
    for name,spec in (('baseline',s),('gap',candidate)):
        result=run_round(spec,g.path,root/name,a.of_root,a.n_procs,600,1_000_000)
        text=(root/name/'logs/snappyHexMesh.log').read_text(errors='replace') if (root/name/'logs/snappyHexMesh.log').exists() else ''
        records.append(dict(arm=name,quality=result.get('quality'),native_error=result.get('error'),gap_log=[x.strip() for x in text.splitlines() if re.search(r'gap|narrow',x,re.I)],spec=spec.to_dict()))
        write_json(root/f'{name}.json',records[-1])
    write_json(root/'summary.json',dict(purpose='synthetic closed-notch stock OpenFOAM tool integration; NOT a model/industrial mesh quality comparison',new_drivaer_attempts=0,paid_api_calls=0,source_unchanged=before==sha256(source),code_sha256=code_hash(),records=records))
    print([dict(arm=x['arm'],cells=(x['quality'] or {}).get('metrics',{}).get('cells'),native_error=x['native_error'],gap_lines=len(x['gap_log'])) for x in records],flush=True)


if __name__=='__main__':main()
