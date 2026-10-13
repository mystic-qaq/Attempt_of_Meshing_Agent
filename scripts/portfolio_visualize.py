"""Render recorded native volume cuts and actual wall-layer fields, without CFD fiction."""
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from cfdmesh.io import read_json, write_json, sha256
from cfdmesh.verify import boundary_scalar, obj_face_geometry

LABELS = dict(ahmed_public_25='Vehicle: Ahmed 25°', finite_wing='Finite wing',
              finite_cylinder='Finite cylinder', submerged_spheroid='Submerged spheroid')
ORIGINS={'deepseek-flash_initial_plan':'LLM initial plan','deepseek-flash':'LLM repair',
         'deterministic_fallback':'Program fallback','archived_model_proposal_validation':'Archived LLM proposal'}


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


def cut_segments(mesh):
    import vtk
    plane = vtk.vtkPlane(); plane.SetOrigin(0, 0, 0); plane.SetNormal(0, 1, 0)
    cut = vtk.vtkCutter(); cut.SetInputData(mesh); cut.SetCutFunction(plane); cut.GenerateTrianglesOff(); cut.Update()
    edges = vtk.vtkExtractEdges(); edges.SetInputConnection(cut.GetOutputPort()); edges.Update()
    data = edges.GetOutput(); segments = []
    for i in range(data.GetNumberOfCells()):
        cell = data.GetCell(i)
        pts = np.array([data.GetPoint(cell.GetPointId(j)) for j in range(cell.GetNumberOfPoints())])
        for j in range(len(pts)-1): segments.append(pts[[j, j+1]][:, [0, 2]])
    return segments


def wall_data(case):
    obj = Path(case) / 'body.obj'; vertices = []; faces = []
    for line in obj.read_text().splitlines():
        if line.startswith('v '): vertices.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('f '): faces.append([int(x.split('/')[0])-1 for x in line.split()[1:]])
    vertices = np.asarray(vertices); areas, _ = obj_face_geometry(obj)
    values, uniform = boundary_scalar(Path(case) / '0/nSurfaceLayers')
    if uniform: values = np.full(len(faces), values[0])
    if len(values) != len(faces): raise ValueError('wall-layer count/polygon mismatch')
    return vertices, faces, values, float(areas[values >= 5].sum()/areas.sum())


def render(report_file, out):
    report = read_json(report_file); out = Path(out); out.mkdir(parents=True, exist_ok=True)
    cases = report['cases']; n = len(cases); manifest = []
    fig, axes = plt.subplots(n, 1, figsize=(11, 2.8*n), squeeze=False)
    for row, c in enumerate(cases):
        ax = axes[row, 0]
        for a in c['attempts']:
            coverage = a['layer_coverage']
            if coverage is None: continue
            colour = '#087f8c' if a['admissible_diagnostic'] else '#bd433a'
            ax.scatter(a['attempt'], coverage*100, c=colour, marker='o' if a['admissible_diagnostic'] else 'x', s=80, linewidth=2)
            cells = f"{a['cells']/1000:.0f}k" if a['cells'] else 'no count'
            ax.annotate(f"{coverage*100:.1f}% / {cells}\n{a['decision_origin']}", (a['attempt'], coverage*100),
                        xytext=(0, 9 if coverage < .85 else -32), textcoords='offset points', ha='center', fontsize=7)
        ax.axhline(90, color='#777', linestyle='--', linewidth=1)
        ax.set_xlim(.5, 5.5); ax.set_ylim(-5, 112); ax.set_xticks(range(1, 6))
        ax.set_ylabel('Wall area with ≥5 layers (%)'); ax.set_title(LABELS[c['id']], loc='left')
        ax.grid(axis='y', alpha=.15)
    axes[-1, 0].set_xlabel('Native mesh attempt (includes archived development history)')
    fig.suptitle('Measured feedback trajectory — rejected attempts remain visible', fontsize=14)
    fig.text(.5, .005, 'Blue: quality/fidelity/scene/budget valid, no pipeline error. Red ×: inadmissible. Dashed line: unchanged 90% gate.', ha='center', fontsize=8)
    fig.tight_layout(rect=[0, .025, 1, .965]); fig.savefig(out/'feedback_trajectory.png', dpi=160); plt.close(fig)

    fig, axes = plt.subplots(n, 2, figsize=(13, 3*n), squeeze=False)
    wall_fig = plt.figure(figsize=(12, 3.4*n))
    for row, c in enumerate(cases):
        baseline = c['baseline']; selected = c['selected']
        crop = None
        if baseline and (Path(baseline['case'])/'body.obj').exists():
            bv, _, _, _ = wall_data(baseline['case'])
            length = np.ptp(bv[:, 0]); height = np.ptp(bv[:, 2]); pad_z = max(height*.65, length*.12)
            crop = (bv[:, 0].min()-.25*length, bv[:, 0].max()+1.4*length,
                    bv[:, 2].min()-pad_z, bv[:, 2].max()+pad_z)
        # No invalid mesh is silently promoted when selection is unavailable.
        for col, (label, a) in enumerate([('One-shot', baseline), ('Selected diagnostic candidate', selected)]):
            ax = axes[row, col]; wall_ax = wall_fig.add_subplot(n, 2, row*2+col+1, projection='3d')
            if not a or not a['cells'] or not (Path(a['case'])/'constant/polyMesh/points').exists():
                ax.text(.5, .5, 'No admissible selection', transform=ax.transAxes, ha='center')
                ax.set_axis_off(); wall_ax.set_axis_off(); continue
            mesh,mesh_hashes = native_grid(a['case'], a['cells']); segments = cut_segments(mesh)
            v, faces, layers, coverage = wall_data(a['case'])
            if not np.isclose(coverage, a['layer_coverage'], atol=1e-10): raise ValueError('rendered wall coverage disagrees with report')
            if crop is None: raise ValueError('paired common crop unavailable')
            lo_x, hi_x, lo_z, hi_z = crop
            ax.add_collection(LineCollection(segments, colors='#294653', linewidths=.28, rasterized=True))
            ax.set_xlim(lo_x, hi_x); ax.set_ylim(lo_z, hi_z); ax.set_aspect('equal'); ax.set_xlabel('X (m)'); ax.set_ylabel('Z (m)')
            qualifier = 'valid diagnostic' if a['admissible_diagnostic'] else 'REJECTED'
            origin=ORIGINS.get(a['decision_origin'],a['decision_origin'])
            ax.set_title(f"{LABELS[c['id']]} — {label}\nAttempt {a['attempt']}, {int(a['cells']):,} cells; {qualifier}\n{origin}", fontsize=9)
            if not a['admissible_diagnostic']:
                ax.text(.01,.02,'Rejected mesh: invalid-cell contours may be omitted by VTK',
                        transform=ax.transAxes,fontsize=6,color='#9c3029',bbox=dict(facecolor='white',alpha=.85,edgecolor='none'))
            colors = np.where((layers >= 5)[:, None], [0.03, .50, .55, 1.], np.where((layers > 0)[:, None], [.94, .64, .16, 1.], [.74, .23, .20, 1.]))
            wall_ax.add_collection3d(Poly3DCollection([v[f] for f in faces], facecolors=colors, edgecolors='none', rasterized=True))
            for axis, column in [('x', 0), ('y', 1), ('z', 2)]:
                getattr(wall_ax, f'set_{axis}lim')(v[:, column].min(), v[:, column].max())
            wall_ax.set_box_aspect(np.ptp(v, axis=0)); wall_ax.view_init(elev=24, azim=-60)
            wall_ax.set_title(f"{LABELS[c['id']]} — {label}\nActual ≥5-layer area: {coverage*100:.2f}%; {qualifier}\n{origin}", fontsize=9)
            wall_ax.set_xlabel('X'); wall_ax.set_ylabel('Y'); wall_ax.set_zlabel('Z')
            manifest.append(dict(case=c['id'], role=label, attempt=a['attempt'], native_cells=mesh.GetNumberOfCells(),
                                 cut_plane='Y=0, XZ projection', layer_coverage=coverage, rejected=not a['admissible_diagnostic'],
                                 native_mesh_sha256=mesh_hashes,readonly_mesh_hashes_unchanged=True))
            manifest[-1]['slice_limitations']='VTK may omit un-contourable non-manifold cells in rejected meshes; the slice is not an exhaustive bad-cell diagnostic'
    fig.suptitle('Actual native volume mesh sections, Y = 0 — common crop within each pair', fontsize=14)
    fig.tight_layout(rect=[0, .025, 1, .96]); fig.savefig(out/'native_mesh_cuts.png', dpi=180); plt.close(fig)
    wall_fig.legend(handles=[Patch(color='#bd3b33', label='0 layers'), Patch(color='#efa329', label='1–4 layers'),
                             Patch(color='#08808c', label='≥5 layers')], loc='lower center', ncol=3, frameon=False)
    wall_fig.suptitle('Native wall polygons coloured by actual nSurfaceLayers', fontsize=14)
    wall_fig.tight_layout(rect=[0, .03, 1, .96]); wall_fig.savefig(out/'native_wall_layers.png', dpi=160); plt.close(wall_fig)
    write_json(out/'visualisation_manifest.json', dict(source='native constant/polyMesh and 0/nSurfaceLayers, no fabricated flow field', records=manifest))
    print('Native figures complete; verified panels:', len(manifest))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('report'); p.add_argument('out')
    args = p.parse_args(); render(args.report, args.out)
