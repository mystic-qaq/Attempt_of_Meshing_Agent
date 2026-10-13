from pathlib import Path
import numpy as np


def spatial_image(geom,diagnoses,path,initial=False,scenario=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Rectangle
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    triangles=geom.mesh.triangles
    # Triangles are explicitly drawn; downsampling is labelled diagnostic only.
    if len(triangles)>250000: triangles=triangles[::max(1,len(triangles)//250000)]
    for ax,(i,j),name in zip(axes,[(0,2),(1,2),(0,1)],['side X/Z','front Y/Z','top X/Y']):
        ax.add_collection(PolyCollection(triangles[:,:,[i,j]],facecolors='#8caec4',
                                          edgecolors='none',alpha=1))
        lo,hi=geom.mesh.bounds[:,[i,j]]
        for r in (scenario or {}).get('requirements',[]):
            a,b=np.array(r['min'])[[i,j]],np.array(r['max'])[[i,j]]
            ax.add_patch(Rectangle(a,*(b-a),fill=False,edgecolor='#187aa3',linestyle='--',linewidth=1.2))
            ax.annotate(r['name'],(a+b)/2,color='#187aa3',fontsize=7)
            lo=np.minimum(lo,a);hi=np.maximum(hi,b)
        for d in diagnoses:
            a,b=np.array(d['min'])[[i,j]],np.array(d['max'])[[i,j]]
            ax.add_patch(Rectangle(a,*(b-a),fill=False,edgecolor='#b8223b',linewidth=1.2))
            c=np.array(d['centroid'])[[i,j]];ax.annotate(d['id'].split(':')[-1],c,color='#b8223b')
        pad=.1*geom.longest;ax.set_xlim(lo[0]-pad,hi[0]+pad);ax.set_ylim(lo[1]-pad,hi[1]+pad)
        ax.set_aspect('equal');ax.set_title(name);ax.set_xlabel('metres');ax.set_ylabel('metres')
    fig.suptitle(('Whole-body input; no native mesh evidence yet' if initial else 'Red boxes = observed issue clusters')+
                 ('; dashed blue = physical hypotheses, not measured flow' if scenario else ''))
    fig.tight_layout();fig.savefig(path,dpi=110);plt.close(fig)
