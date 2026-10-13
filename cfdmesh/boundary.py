"""Observe native OBJ polygons without welding unrelated internal diagonals.

This is a representation change, never hole filling or a change to polyMesh.
Non-simple faces and excessive warp remain unavailable. Simple non-star polygons
use verified ear clipping of their original vertices, preserving concave outlines.
"""
from collections import Counter
from pathlib import Path
import numpy as np
import trimesh


def read_polygons(path):
    vertices=[];faces=[]
    for line in Path(path).read_text().splitlines():
        p=line.split()
        if not p:continue
        if p[0]=='v':vertices.append([float(x) for x in p[1:4]])
        elif p[0]=='f':
            face=[int(x.split('/')[0]) for x in p[1:]]
            face=[x-1 if x>0 else len(vertices)+x for x in face]
            if len(face)<3 or len(set(face))!=len(face):raise ValueError('invalid/repeated polygon vertex')
            faces.append(face)
    v=np.asarray(vertices,float)
    if v.ndim!=2 or v.shape[1]!=3 or not np.isfinite(v).all() or not faces:raise ValueError('empty/nonfinite polygon surface')
    if any(min(p)<0 or max(p)>=len(v) for p in faces):raise ValueError('polygon index out of range')
    return v,faces


def cross2(a,b):return a[0]*b[1]-a[1]*b[0]


def simple_polygon(q):
    size=float(np.ptp(q,axis=0).max());eps=max(size*size*1e-12,1e-28)
    for i in range(len(q)):
        a=q[i];b=q[(i+1)%len(q)]
        if np.dot(b-a,b-a)<=eps:raise ValueError('degenerate native polygon edge')
        for j in range(i+1,len(q)):
            if j==i+1 or (i==0 and j==len(q)-1):continue
            c=q[j];d=q[(j+1)%len(q)]
            s=[cross2(b-a,c-a),cross2(b-a,d-a),cross2(d-c,a-c),cross2(d-c,b-c)]
            if s[0]*s[1]<-eps*eps and s[2]*s[3]<-eps*eps:raise ValueError('self-crossing native polygon')
            for point,u,v,side in ((c,a,b,s[0]),(d,a,b,s[1]),(a,c,d,s[2]),(b,c,d,s[3])):
                if abs(side)<=eps and np.dot(point-u,point-v)<=eps:raise ValueError('nonadjacent native polygon edges touch')
    return eps


def ear_triangles(q):
    """Triangulate a simple CCW polygon without inserting vertices or filling its notch."""
    eps=simple_polygon(q);remaining=list(range(len(q)));tri=[]
    area=sum(cross2(a,b) for a,b in zip(q,np.roll(q,-1,axis=0)))
    if area<=eps:raise ValueError('native polygon orientation/area invalid')
    while len(remaining)>3:
        for k,b in enumerate(remaining):
            a=remaining[k-1];c=remaining[(k+1)%len(remaining)]
            if cross2(q[b]-q[a],q[c]-q[a])<=eps:continue
            if any(all(cross2(q[v]-q[u],q[p]-q[u])>=-eps for u,v in ((a,b),(b,c),(c,a)))
                   for p in remaining if p not in (a,b,c)):continue
            tri.append([a,b,c]);remaining.pop(k);break
        else:raise ValueError('native polygon has no verified nondegenerate ear')
    tri.append(remaining)
    signed=[cross2(q[b]-q[a],q[c]-q[a]) for a,b,c in tri]
    if min(signed)<=eps or abs(sum(signed)-area)>max(abs(area)*1e-9,eps*len(q)):
        raise ValueError('native polygon triangulation area/orientation mismatch')
    return tri


def kernel_point(q):
    """Strict interior of every oriented edge half-plane of a simple CCW polygon."""
    size=float(np.ptp(q,axis=0).max());eps=max(size*size*1e-12,1e-28)
    if len(q)>4:
        for i in range(len(q)):
            a=q[i];b=q[(i+1)%len(q)]
            for j in range(i+1,len(q)):
                if j==i+1 or (i==0 and j==len(q)-1):continue
                c=q[j];d=q[(j+1)%len(q)]
                s=[cross2(b-a,c-a),cross2(b-a,d-a),cross2(d-c,a-c),cross2(d-c,b-c)]
                if s[0]*s[1]<-eps*eps and s[2]*s[3]<-eps*eps:raise ValueError('self-crossing native polygon')
                for point,u,v,side in ((c,a,b,s[0]),(d,a,b,s[1]),(a,c,d,s[2]),(b,c,d,s[3])):
                    if abs(side)<=eps and np.dot(point-u,point-v)<=eps:raise ValueError('nonadjacent native polygon edges touch')
    centre=q.mean(axis=0)
    if all(cross2(b-a,centre-a)>eps for a,b in zip(q,np.roll(q,-1,axis=0))):return centre
    lo=q.min(axis=0)-size;hi=q.max(axis=0)+size
    kernel=[lo,[hi[0],lo[1]],hi,[lo[0],hi[1]]]
    kernel=[np.array(x,float) for x in kernel]
    for a,b in zip(q,np.roll(q,-1,axis=0)):
        clipped=[]
        for u,v in zip(kernel,kernel[1:]+kernel[:1]):
            su=cross2(b-a,u-a);sv=cross2(b-a,v-a)
            if su>=0:clipped.append(u)
            if (su>=0)!=(sv>=0):clipped.append(u+(v-u)*su/(su-sv))
        kernel=clipped
        if not kernel:raise ValueError('native polygon has no verified star-shaped triangulation')
    centre=np.mean(kernel,axis=0)
    if not all(cross2(b-a,centre-a)>eps for a,b in zip(q,np.roll(q,-1,axis=0))):raise ValueError('native polygon kernel has no strict interior')
    return centre


def polygon_geometry(path):
    """Native vector areas, preserving one value per original boundary face."""
    vertices,faces=read_polygons(path);areas=[];centres=[]
    for face in faces:
        q=vertices[face];c=q.mean(axis=0)
        area=np.linalg.norm(np.cross(q-c,np.roll(q,-1,axis=0)-c).sum(axis=0))*.5
        if not np.isfinite(area) or area<=0:raise ValueError('nonpositive native polygon vector area')
        areas.append(area);centres.append(c)
    return np.array(areas),np.array(centres)


def observe(path):
    vertices,polys=read_polygons(path);v=vertices.tolist();triangles=[];parent=[]
    edges=Counter();directions=Counter();max_warp=0.
    for face in polys:
        for a,b in zip(face,face[1:]+face[:1]):
            key=tuple(sorted((a,b)));edges[key]+=1;directions[key]+=1 if a<b else -1
    if any(n!=2 for n in edges.values()):raise ValueError('native polygon boundary has open/nonmanifold edges')
    if any(n!=0 for n in directions.values()):raise ValueError('native polygon orientation inconsistent')
    for index,face in enumerate(polys):
        q=vertices[face];c=q.mean(axis=0);relative=q-c
        normal=np.cross(relative,np.roll(relative,-1,axis=0)).sum(axis=0)
        length=np.linalg.norm(normal)
        if length<=0:raise ValueError('zero native polygon vector area')
        normal/=length;axis=np.eye(3)[np.argmin(np.abs(normal))]
        x=np.cross(axis,normal);x/=np.linalg.norm(x);y=np.cross(normal,x)
        projected=np.column_stack((relative@x,relative@y))
        warp=float(np.max(np.abs(relative@normal))/max(np.linalg.norm(np.ptp(q,axis=0)),1e-30));max_warp=max(max_warp,warp)
        context=f'boundary face {index} bbox {q.min(axis=0).tolist()} .. {q.max(axis=0).tolist()}'
        if warp>.2:raise ValueError(context+': native polygon too warped for faithful planar-kernel observation')
        if len(face)==3:
            triangles.append(face);parent.append(index);continue
        try:p=kernel_point(projected)
        except ValueError:
            try:ears=ear_triangles(projected)
            except ValueError as exc:raise ValueError(context+': projected '+str(exc)) from exc
            for t in ears:triangles.append([face[i] for i in t]);parent.append(index)
            continue
        centre=c+p[0]*x+p[1]*y;mid=len(v);v.append(centre.tolist())
        for a,b in zip(face,face[1:]+face[:1]):triangles.append([a,b,mid]);parent.append(index)
    mesh=trimesh.Trimesh(vertices=np.array(v),faces=np.array(triangles),process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or np.any(mesh.area_faces<=0):raise ValueError('observed triangle surface fails closure/orientation/area')
    report=dict(available=True,native_polygon_closed=True,native_polygon_oriented=True,
        polygons=len(polys),triangles=len(triangles),max_relative_face_warp=max_warp,
        triangulation='verified visibility kernel or simple-polygon ear clipping; no welding or hole filling',
        limitation='representation of native polygons; self-intersection requires separate native surfaceCheck; no polyMesh change')
    return mesh,report,np.array(parent)
