"""Native internal-mesh cuts and whole-wall layer maps with verified mesh hashes."""
import argparse
from pathlib import Path
import numpy as np
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from cfdmesh.io import read_json,write_json,sha256
from scripts.portfolio_visualize import native_grid,wall_data

def segments(mesh,y):
    import vtk
    plane=vtk.vtkPlane();plane.SetOrigin(0,y,0);plane.SetNormal(0,1,0)
    cut=vtk.vtkCutter();cut.SetInputData(mesh);cut.SetCutFunction(plane);cut.GenerateTrianglesOff();cut.Update()
    edges=vtk.vtkExtractEdges();edges.SetInputConnection(cut.GetOutputPort());edges.Update()
    obj=edges.GetOutput();lines=[]
    for i in range(obj.GetNumberOfCells()):
        cell=obj.GetCell(i)
        pts=np.array([obj.GetPoint(cell.GetPointId(j)) for j in range(cell.GetNumberOfPoints())])
        lines.extend(pts[[j,j+1]][:,[0,2]] for j in range(len(pts)-1))
    return lines

def render_case(a,out):
    case=Path(a['case']);label=f'{a["arm"]} attempt {a["attempt"]}'
    qualifier='admissible mesh diagnostic' if a['admissible_diagnostic'] else 'REJECTED diagnostic'
    v,faces,layers,coverage=wall_data(case)
    if not np.isclose(coverage,a['coverage_ge5'],atol=1e-10):raise ValueError('wall metric mismatch')
    mesh,hashes=native_grid(case,a['cells']);box=np.array([v.min(axis=0),v.max(axis=0)])
    fig,axes=plt.subplots(2,2,figsize=(16,9))
    for row,y in enumerate([0.,.65]):
        lines=segments(mesh,y)
        for col,ax in enumerate(axes[row]):
            ax.add_collection(LineCollection(lines,colors='#234252',linewidths=.25 if col==0 else .45,rasterized=True))
            if col==0:
                ax.set_xlim(box[0,0]-1.,box[1,0]+5.);ax.set_ylim(box[0,2]-.5,box[1,2]+.5)
            else:
                ax.set_xlim(-1.9,-1.1);ax.set_ylim(-.85,-.15)
            ax.set_aspect('equal');ax.set_xlabel('X (m), centred source frame');ax.set_ylabel('Z (m)')
            ax.set_title(f'Y={y:.2f} m; '+('body and near wake' if col==0 else 'front wheel / underbody detail'))
    fig.suptitle(f'{label}: {int(a["cells"]):,} native cells; {qualifier}\nActual >=5-layer body area: {coverage*100:.2f}%; these are real mesh edges, not a flow field')
    fig.text(.5,.01,'VTK may omit contours of malformed polyhedral cells in rejected meshes; cuts do not certify topology.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.025,1,.94]);fig.savefig(out/f'{a["arm"]}_round{a["round"]}_cuts.png',dpi=170);plt.close(fig)
    del mesh
    polygons=[v[f] for f in faces];colours=np.where(layers>=5,'#2388c3',np.where(layers>=1,'#edb140','#cd3f45'))
    fig=plt.figure(figsize=(16,8))
    for i,(elev,azim) in enumerate([(22,-65),(-25,-65)]):
        ax=fig.add_subplot(1,2,i+1,projection='3d')
        ax.add_collection3d(Poly3DCollection(polygons,facecolors=colours,edgecolors='none',linewidths=0,rasterized=True))
        ax.set_xlim(box[:,0]);ax.set_ylim(box[:,1]);ax.set_zlim(box[:,2]);ax.set_box_aspect(box[1]-box[0]);ax.view_init(elev=elev,azim=azim)
        ax.set_xlabel('X (m)');ax.set_ylabel('Y (m)');ax.set_zlabel('Z (m)');ax.set_title('Upper view' if i==0 else 'Underbody view')
    fig.legend(handles=[Patch(color='#2388c3',label='>=5 native layers'),Patch(color='#edb140',label='1-4 native layers'),Patch(color='#cd3f45',label='0 native layers')],loc='lower center',ncol=3)
    fig.suptitle(f'{label}: actual wall-layer map; >=5 layer area {coverage*100:.2f}%\n{qualifier}; full wall polygons rendered; no synthetic geometry')
    fig.tight_layout(rect=[0,.04,1,.95]);fig.savefig(out/f'{a["arm"]}_round{a["round"]}_layers.png',dpi=160);plt.close(fig)
    for name,digest in hashes.items():
        if sha256(case/'constant/polyMesh'/name)!=digest:raise ValueError('native mesh modified by rendering')
    return dict(arm=a['arm'],round=a['round'],case=str(case),polyMesh_sha256=hashes,native_cells=a['cells'],area_coverage_ge5=coverage,
                contour_limitation='VTK can omit malformed polyhedral cell contours, especially on rejected meshes; no topology certification from plots.')

def main():
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--arm',choices=['agent','expert']);p.add_argument('--round',type=int);a=p.parse_args();root=Path(a.root)
    report=read_json(root/'results/comparison.json');out=root/'results/assets';out.mkdir(parents=True,exist_ok=True)
    attempts=[x for x in report['attempts'] if (a.arm is None or x['arm']==a.arm) and (a.round is None or x['round']==a.round)]
    if a.round is None:
        attempts=[x for x in attempts if x['round']==report['selected_round'].get(x['arm'])]
    manifests=[]
    for x in attempts:
        if not x['cells'] or not (Path(x['case'])/'body.obj').exists():continue
        manifests.append(render_case(x,out))
    write_json(out/f'render_manifest_{a.arm or "both"}_{a.round if a.round is not None else "selected"}.json',manifests)
    print('rendered',[(x['arm'],x['round']) for x in manifests],flush=True)

if __name__=='__main__':main()
