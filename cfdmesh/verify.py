from __future__ import annotations
import math
import re
from pathlib import Path
import numpy as np
from .planning import clusters, finest_size

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def surface_report(text,returncode=0):
    closed='Surface is closed. All edges connected to two faces.' in text
    nonintersecting='Surface is not self-intersecting' in text
    intersections=re.search(r'Surface is self-intersecting at\s+(\d+)\s+locations',text)
    reasons=[]
    if returncode!=0 or 'FOAM FATAL' in text or not re.search(r'^\s*End\s*$',text,re.M):reasons.append('native surface check incomplete')
    if not closed:reasons.append('native surface closure not affirmative')
    if not nonintersecting:reasons.append('native self-intersection check failed/unavailable')
    return dict(accepted=not reasons,reasons=reasons,closed=closed,self_intersection_free=nonintersecting,
                self_intersection_locations=int(intersections.group(1)) if intersections else None)


def quality_report(text, returncode=0):
    def number(pattern):
        m = re.search(pattern,text,re.M|re.I)
        return float(m.group(1)) if m else None
    failed = re.findall(r'Failed\s+(\d+)\s+mesh checks',text,re.I)
    ok = bool(re.search(r'^\s*Mesh OK\.?\s*$',text,re.M))
    complete = (ok or bool(failed)) and bool(re.search(r'^\s*End\s*$',text,re.M))
    fatal = bool(re.search(r'FOAM FATAL|FOAM aborting|Illegal field|\*\*\* KILLED',text,re.I))
    # Native point-fan warnings can be appended immediately after Points, before
    # the topology status. Limit parsing to the actual table, preserve body count,
    # and reject the real topology defect instead of reporting a missing body.
    table=text.split('Checking patch topology for multiply connected surfaces...',1)[-1].split('Checking geometry...',1)[0]
    patches={m.group(1):int(m.group(2)) for m in re.finditer(
        r'^\s*([A-Za-z_][\w.-]*)\s+(\d+)\s+\d+(?=\s|Point\b)',table,re.M)}
    point_fan_warning=bool(re.search(r'Point\s+\d+\s+uses faces which are not connected through an edge',table))
    body_shared_edge=bool(re.search(r'^\s*body\s+\d+\s+\d+\s+multiply connected \(shared edge\)',table,re.M))
    metrics=dict(cells=number(r'^\s*cells:\s*(\d+)'),
                 regions=number(r'Number of regions:\s*(\d+)'),
                 max_non_ortho=number(r'Mesh non-orthogonality Max:\s*('+NUM+')'),
                 max_skew=number(r'Max skewness\s*=\s*('+NUM+')'),
                 max_aspect=number(r'Max aspect ratio\s*[=:]\s*('+NUM+')'),
                 min_volume=number(r'(?:Min volume\s*=|Minimum negative volume:)\s*('+NUM+')'))
    missing=[k for k,v in metrics.items() if v is None or not math.isfinite(v)]
    n_failed=int(failed[-1]) if failed else (0 if ok else None)
    messages=[line.strip() for line in text.splitlines()
              if re.search(r'\*\*\*|failed|negative volume|zero area',line,re.I)]
    reasons=[]
    native_times=re.findall(r'^\s*Time =\s*(\S+)\s*$',text,re.M)
    final_only=not native_times or native_times==['constant']
    if not final_only:reasons.append('mesh check includes non-final or multiple time states')
    if not complete or fatal or returncode != 0:
        reasons.append('native checkMesh did not successfully complete')
    if missing:
        reasons.append('required quality evidence missing: '+', '.join(missing))
    if n_failed != 0:
        reasons.append(f'native checkMesh failed checks: {n_failed}; unknown failures are never ignored')
    if patches.get('body',0)<=0:
        reasons.append('nonempty body boundary absent')
    if point_fan_warning:reasons.append('native boundary has disconnected face fans at a shared point')
    if body_shared_edge:reasons.append('native body boundary has multiply connected shared edges')
    if metrics['regions'] != 1:
        reasons.append('fluid region is not single connected')
    for key,limit in [('max_non_ortho',70),('max_skew',4),('max_aspect',1000)]:
        if metrics[key] is not None and metrics[key] > limit:
            reasons.append(f'{key} exceeds RANS quality limit {limit}')
    if metrics['min_volume'] is not None and metrics['min_volume'] <= 0:
        reasons.append('nonpositive cell volume')
    return dict(verified=complete and not fatal and returncode==0 and final_only,accepted=not reasons,
                reasons=reasons,n_failed=n_failed,metrics=metrics,patches=patches,
                native_failure_messages=messages,returncode=returncode,native_times=native_times,
                boundary_disconnected_point_fans=point_fan_warning,body_shared_edge_defect=body_shared_edge)


def read_vtk_centres(path):
    """Handles faceSets AND cellSets, ASCII/binary legacy and XML VTK."""
    path=Path(path)
    try:
        import vtk
        if path.suffix=='.vtp':
            reader=vtk.vtkXMLPolyDataReader()
        elif path.suffix=='.vtu':
            reader=vtk.vtkXMLUnstructuredGridReader()
        else:
            reader=vtk.vtkGenericDataObjectReader()
        reader.SetFileName(str(path));reader.Update()
        data=reader.GetOutput()
        if data.GetNumberOfCells()==0 and data.GetNumberOfPoints()>0:
            return np.array([data.GetPoint(i) for i in range(data.GetNumberOfPoints())]).reshape(-1,3)
        result=[]
        for i in range(data.GetNumberOfCells()):
            cell=data.GetCell(i)
            result.append(np.mean([data.GetPoint(cell.GetPointId(j)) for j in range(cell.GetNumberOfPoints())],axis=0))
        return np.asarray(result).reshape(-1,3)
    except ImportError:
        pass
    # Portable tests/fallback: conventional legacy ASCII polygons or cells.
    text=path.read_text(errors='replace')
    if not re.search(r'^ASCII\s*$',text,re.M):
        raise ValueError('binary VTK requires the vtk dependency')
    p=re.search(r'^POINTS\s+(\d+)\s+\w+\s*\n',text,re.M)
    if not p: raise ValueError('VTK POINTS missing')
    count=int(p.group(1)); tokens=text[p.end():].split()
    xyz=np.array([float(v) for v in tokens[:3*count]]).reshape(-1,3)
    m=re.search(r'^(CELLS|POLYGONS|LINES|VERTICES)\s+(\d+)\s+(\d+)\s*\n',text,re.M)
    if not m: raise ValueError('VTK connectivity missing')
    data=[int(v) for v in text[m.end():].split()[:int(m.group(3))]]
    centres=[];offset=0
    for _ in range(int(m.group(2))):
        length=data[offset]; idx=data[offset+1:offset+1+length];offset+=1+length
        centres.append(xyz[idx].mean(axis=0))
    return np.asarray(centres).reshape(-1,3)


def spatial_diagnostics(case, geom, spec, fidelity_bad=None,layer_bad=None):
    result=[]; errors=[]; h=finest_size(spec,geom)
    sets=[]
    for ext in ('*.vtk','*.vtp','*.vtu'):
        for p in Path(case).rglob(ext):
            if any(x in p.stem.lower() for x in ('skew','nonortho','concav','wrong','illegal','negative','zerovolume','highaspect','quality','volratio','weight','determinant','nonmanifold')):
                sets.append((str(p.relative_to(case)),p))
    if fidelity_bad:
        sets.append(('fidelity_loss',np.asarray(fidelity_bad)))
    if layer_bad:
        sets.insert(0,('layer_shortfall',np.asarray(layer_bad)))
    for tag,p in sets:
        try:
            points=p if isinstance(p,np.ndarray) else read_vtk_centres(p)
            for cluster in clusters(points,4*h,8):
                if not len(cluster): continue
                _,dist,_=geom.nearest(cluster)
                feature=geom.local_feature(cluster)
                finite=feature[np.isfinite(feature)]
                gap=float(np.median(finite)*2) if len(finite) else None
                median=float(np.median(dist))
                cause='boundary_topology' if 'nonmanifold' in tag.lower() else tag if tag in ('fidelity_loss','layer_shortfall') else (
                    'underresolved_feature' if median<3*h and gap is not None and gap<6*h else
                    'snap_artifact' if median<3*h else 'transition' if median<24*h else 'farfield')
                result.append(dict(id=f'{tag}:{len(result)}',cause=cause,cause_status='diagnostic class; geometric cause is a hypothesis requiring regional/native corroboration',count=len(cluster),
                    median_wall_distance=median,measured_local_full_feature=gap,
                    feature_quantity='resolution proxy: 2*min(solid normal half-thickness, outward normal-ray gap/2); not native external-fluid medial distance or available layer space',
                    min=(cluster.min(axis=0)-2*h).tolist(),max=(cluster.max(axis=0)+2*h).tolist(),
                    centroid=cluster.mean(axis=0).tolist(),metric=tag))
        except Exception as e:
            errors.append(dict(file=str(p),error=f'{type(e).__name__}: {e}'))
    return result,errors


def boundary_scalar(path,patch='body'):
    """Read uniform or nonuniform scalar boundary values, including native binary."""
    raw=Path(path).read_bytes()
    start=raw.find(b'boundaryField')
    if start<0: raise ValueError('field boundary data absent')
    match=re.search(rb'\b'+patch.encode()+rb'\s*\{',raw[start:])
    if not match: raise ValueError('body boundary field absent')
    begin=start+match.end()
    # Native binary may contain brace bytes: do not use brace balancing on the payload.
    segment=raw[begin:]
    uniform=re.match(rb'\s*type\s+\w+;\s*value\s+uniform\s+('+NUM.encode()+rb')\s*;',segment)
    if uniform: return np.array([float(uniform.group(1))]),True
    value=re.search(rb'\bvalue\s+nonuniform\s+List<scalar>\s+(\d+)\s*\(',segment)
    if not value: raise ValueError('unsupported body scalar field syntax')
    n=int(value.group(1));payload=segment[value.end():]
    is_binary=bool(re.search(rb'\bformat\s+binary\s*;',raw[:2000]))
    if is_binary:
        # OpenFOAM binary list inserts exactly one newline before packed values.
        little=b'LSB' in raw[:2000];bits=32 if b'scalar=32' in raw[:2000] else 64
        size=n*bits//8
        if not payload[size:].lstrip().startswith(b')'):
            if payload.startswith(b'\r\n') and payload[size+2:].lstrip().startswith(b')'): payload=payload[2:]
            elif payload.startswith(b'\n') and payload[size+1:].lstrip().startswith(b')'): payload=payload[1:]
            else: raise ValueError('binary scalar list size/terminator inconsistent')
        return np.frombuffer(payload[:n*bits//8],dtype=('<' if little else '>')+f'f{bits//8}').copy(),False
    return np.fromstring(payload.split(b')',1)[0].decode(),sep=' ')[:n],False


def obj_face_geometry(path):
    from .boundary import polygon_geometry
    return polygon_geometry(path)


def obj_face_areas(path):
    return obj_face_geometry(path)[0]


def layer_report(case, surface, physics, log,expansion_ratio=None):
    case=Path(case);candidates=[]
    for p in case.glob('*/nSurfaceLayers'):
        if p.parent.name.replace('.','',1).isdigit(): candidates.append(p)
    reasons=[]
    if not candidates:
        return dict(available=False,accepted=False,reasons=['actual nSurfaceLayers boundary field unavailable'])
    try:
        p=max(candidates,key=lambda p:float(p.parent.name))
        values,uniform=boundary_scalar(p)
        areas,centres=obj_face_geometry(surface)
        if uniform: values=np.full(len(areas),values[0])
        if len(values)!=len(areas) or not len(values) or not np.isfinite(values).all():
            raise ValueError('layer values and body face areas do not match')
        if np.any(values<0) or not np.allclose(values,np.rint(values),rtol=0,atol=1e-8):
            raise ValueError('native layer counts must be nonnegative integers')
        if not np.isfinite(areas).all() or np.any(areas<=0):
            raise ValueError('invalid native wall face areas')
        coverage=float(areas[values>=5].sum()/areas.sum())
        counts={str(int(i)):float(areas[values==i].sum()/areas.sum()) for i in np.unique(values)}
        thickness_path=p.with_name('thickness')
        first_stats=None;yplus_stats=None;area_first=None;area_yplus=None
        if thickness_path.exists():
            thickness,unif=boundary_scalar(thickness_path)
            if unif: thickness=np.full(len(areas),thickness[0])
            if len(thickness)==len(values):
                if not np.isfinite(thickness).all() or np.any(thickness[values>=5]<=0):
                    raise ValueError('native thickness must be finite and positive on covered faces')
                good=values>=5;r=expansion_ratio or physics['expansion_ratio']
                if not np.isfinite(r) or r<=1:raise ValueError('unsupported layer expansion ratio')
                first=thickness[good]*(r-1)/(r**values[good]-1)
                yplus=first*.5*physics['estimated_utau']/physics['nu']
                first_stats={f'p{q}':float(np.percentile(first,q)) for q in (5,50,95)} if len(first) else None
                yplus_stats={f'p{q}':float(np.percentile(yplus,q)) for q in (5,50,95)} if len(yplus) else None
                if len(first):
                    order=np.argsort(first);cumulative=np.cumsum(areas[good][order]);cumulative/=cumulative[-1]
                    area_first={f'p{q}':float(first[order][min(np.searchsorted(cumulative,q/100),len(first)-1)]) for q in (5,50,95)}
                    area_yplus={key:value*.5*physics['estimated_utau']/physics['nu'] for key,value in area_first.items()}
        if coverage<.90: reasons.append('less than 90% body area has at least 5 actual layers')
        if yplus_stats is None: reasons.append('actual layer thickness unavailable')
        elif yplus_stats['p5']<30 or yplus_stats['p95']>300:
            reasons.append('estimated y+ distribution outside wall-function target 30..300')
        return dict(available=True,accepted=not reasons,reasons=reasons,coverage=coverage,
                    minimum_layers=5,required_area_fraction=.90,area_fraction_by_layers=counts,
                    first_height=first_stats,estimated_yplus=yplus_stats,
                    area_weighted_inferred_first_height=area_first,area_weighted_estimated_yplus=area_yplus,
                    thickness_inference='first height inferred from final total thickness/count assuming one geometric progression; not direct cell-wall distance and may be inaccurate for sliced outer passes',
                    actual_yplus='unavailable_without_flow',field=str(p),
                    bad_layer_points=centres[values<5][::max(1,int(np.sum(values<5))//4096)][:4096].tolist(),
                    limitations='near-wall planning gate using flat-plate u_tau; not a physical validation')
    except Exception as e:
        return dict(available=False,accepted=False,reasons=[f'{type(e).__name__}: {e}'])
