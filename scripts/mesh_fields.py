"""Read native volume cells and wall-layer fields for DrivAer figures."""
from pathlib import Path
import numpy as np
from cfdmesh.io import sha256
from cfdmesh.verify import boundary_scalar, obj_face_geometry


def native_grid(case, expected_cells):
    import vtk
    folder=Path(case)/'constant/polyMesh'
    hashes={name:sha256(folder/name) for name in ('points','faces','owner','neighbour','boundary')}
    marker = Path(case) / 'scenario_mesh.foam'
    marker.touch()
    reader = vtk.vtkOpenFOAMReader(); reader.SetFileName(str(marker)); reader.UpdateInformation()
    reader.DisableAllPatchArrays(); reader.SetPatchArrayStatus('internalMesh', 1)
    reader.DisableAllCellArrays(); reader.Update()
    def blocks(obj):
        if isinstance(obj, vtk.vtkUnstructuredGrid): yield obj
        elif isinstance(obj, vtk.vtkMultiBlockDataSet):
            for i in range(obj.GetNumberOfBlocks()): yield from blocks(obj.GetBlock(i))
    mesh = next(blocks(reader.GetOutput()), None)
    if mesh is None or mesh.GetNumberOfCells() != int(expected_cells):
        raise ValueError('visualisation reader cell count does not match native CheckMesh')
    if any(sha256(folder/name)!=digest for name,digest in hashes.items()):
        raise ValueError('native mesh changed during read-only rendering')
    return mesh,hashes


def wall_data(case):
    obj = Path(case) / 'body.obj'; vertices = []; faces = []
    for line in obj.read_text().splitlines():
        if line.startswith('v '): vertices.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('f '): faces.append([int(x.split('/')[0])-1 for x in line.split()[1:]])
    vertices = np.asarray(vertices); areas, _ = obj_face_geometry(obj)
    fields=[p for p in Path(case).glob('*/nSurfaceLayers') if p.parent.name.replace('.','',1).isdigit()]
    if not fields:raise ValueError('native wall-layer field unavailable')
    values, uniform = boundary_scalar(max(fields,key=lambda p:float(p.parent.name)))
    if uniform: values = np.full(len(faces), values[0])
    if len(values) != len(faces): raise ValueError('wall-layer count/polygon mismatch')
    return vertices, faces, values, float(areas[values >= 5].sum()/areas.sum())
