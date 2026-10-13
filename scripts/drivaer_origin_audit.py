"""Read-only input-origin sensitivity audit; never a surface repair or mesh run."""
import argparse
import time
from pathlib import Path
import numpy as np
import trimesh
from cfdmesh.io import sha256,write_json
from cfdmesh.runner import command,environment
from cfdmesh.verify import surface_report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('out');p.add_argument('--of-root',required=True)
    a=p.parse_args();source=Path(a.source);out=Path(a.out)
    if out.exists():raise FileExistsError('origin audit must be fresh')
    out.mkdir();before=sha256(source);mesh=trimesh.load(source,force='mesh',process=False)
    vertices=np.asarray(mesh.vertices).copy();lo,hi=mesh.bounds
    origins=[('source',np.zeros(3)),('bbox_min',lo),('bbox_max',hi),('bbox_centre',(lo+hi)/2)]
    records=[]
    for name,origin in origins:
        folder=out/name;folder.mkdir();m=mesh.copy();m.apply_translation(-origin)
        transformed=folder/'body.stl';transformed.write_text(trimesh.exchange.stl.export_stl_ascii(m))
        inverse_error=float(np.max(np.abs(m.vertices+origin-vertices)))
        step,text=command([Path(a.of_root)/'bin/surfaceCheck','-checkSelfIntersection','body.stl'],
            folder,environment(a.of_root),folder/'surfaceCheck.log',time.monotonic()+300)
        records.append(dict(name=name,origin_in_source_metres=origin.tolist(),inverse_max_error=inverse_error,
            triangles=len(m.faces),transformed_sha256=sha256(transformed),native=surface_report(text,step['returncode'])))
        write_json(out/'audit.json',dict(source_sha256=before,source_mutated=sha256(source)!=before,
            operation='whole-surface rigid translations only; all triangles preserved; not proof of absence of mathematical intersections',records=records))
        print(name,records[-1]['native'],flush=True)
