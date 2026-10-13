"""Read-only regional density check on the two existing stock-native smoke meshes."""
import argparse
from pathlib import Path
from cfdmesh.scenario import native_screen
from cfdmesh.io import read_json,write_json,sha256


def main():
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();root=Path(a.directory)
    old=read_json(root/'summary.json');result=[]
    scene={'requirements':[dict(id='notch_fluid_roi',min=[-.025,-.1,-.1],max=[.025,.2,.1],max_cell_axis_span_metres=.02,native_p95_tolerance=1)]}
    for record in old['records']:
        case=root/record['arm'];paths=[case/'constant/polyMesh'/n for n in ('points','faces','owner','neighbour','boundary')]
        before={p.name:sha256(p) for p in paths};measurement=native_screen(case,scene)
        if measurement['native_total_cells']!=record['quality']['metrics']['cells']:raise ValueError('VTK/native count mismatch')
        if before!={p.name:sha256(p) for p in paths}:raise ValueError('read-only measurement changed native mesh')
        result.append(dict(arm=record['arm'],roi=measurement['requirements'][0],native_polyMesh_unchanged=True))
    write_json(root/'roi_measurement.json',dict(purpose='cached closed-notch native density integration; ROI is an explicit geometric box, not a flow or industrial accuracy validation',records=result))
    print(result,flush=True)


if __name__=='__main__':main()
