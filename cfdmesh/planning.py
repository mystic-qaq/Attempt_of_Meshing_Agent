from __future__ import annotations
import copy
import math
import re
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from .case_builder import (MeshSpec, DomainSpec, SurfaceRefinement, FeatureSpec,
                           LayerSpec, DistanceLevel, RefinementRegion, SnapSpec)
from .candidates import plan_id,eligible

LAYER_PARAMETERS={
    'mesh_shrinker':('displacementMedialAxis','displacementMotionSolver'),
    'feature_angle':(30,170),'slip_feature_angle':(0,90),
    'merge_patch_faces_angle':(10,90),'n_surface_layers':(5,16),
    'expansion_ratio':(1.05,1.35),'n_grow':(0,3),
    'n_smooth_surface_normals':(1,8),'n_smooth_normals':(1,15),
    'n_smooth_thickness':(1,30),'n_relax_iter':(1,15),
    'n_layer_iter':(20,100),'n_outer_iter':(1,5),
    'max_face_thickness_ratio':(.2,1),'max_thickness_to_medial_ratio':(.1,.6),
    'min_medial_axis_angle':(30,130),'n_buffer_cells_no_extrude':(0,3),
    'layer_termination_angle':(-180,180),'detect_extrusion_island':(False,True)}
SNAP_PARAMETERS={'n_smooth_patch':(1,10),'tolerance':(.5,4),
    'n_solve_iter':(20,100),'n_relax_iter':(3,15),'n_feature_snap_iter':(5,30),
    'implicit_feature_snap':(False,True),'explicit_feature_snap':(False,True),
    'n_face_split_interval':(-1,30),'avoid_diagonal':(False,True),
    'concave_angle':(10,90),'min_area_ratio':(.05,.8)}
GENERATION_QUALITY_PARAMETERS={'max_boundary_skewness':(.5,4.),
    'max_internal_skewness':(.5,4.),'max_non_ortho':(30.,65.),'max_concave':(10.,80.),
    'min_tet_quality':(1e-15,1e-6),'min_face_weight':(.05,.25),
    'min_vol_ratio':(.01,.5),'min_determinant':(.001,.1),'min_twist':(.02,.5),
    'min_triangle_twist':(0.,.5)}
RESOLUTION_PARAMETERS={'surface_level':(1,9),'base_cells':(4,24)}
BAND_PARAMETERS={'inner_distance':(1e-9,1e6),'outer_distance':(1e-9,1e6)}


def normalise_actions(actions,valid_ids):
    """Losslessly package known parameter fields and resolve evidence citations.

    Numerical values and coordinates are never changed. Full raw advice is retained.
    Unknown spatial IDs still fail; explanatory strings are recorded as notes.
    """
    result=copy.deepcopy(actions);notes=[]
    if not isinstance(result,list):raise ValueError('actions must be a list')
    for action in result:
        schema={'layer_settings':LAYER_PARAMETERS,'snap_settings':SNAP_PARAMETERS,
                'resolution_settings':RESOLUTION_PARAMETERS,'refinement_bands':BAND_PARAMETERS,
                'generation_quality':GENERATION_QUALITY_PARAMETERS}.get(action.get('kind'))
        if schema:
            flat={k:action[k] for k in schema if k in action}
            if flat:
                nested=action.get('parameters',{})
                if not isinstance(nested,dict):raise ValueError('parameters must be an object')
                if any(k in nested and nested[k]!=v for k,v in flat.items()):raise ValueError('conflicting flattened/nested parameter values')
                action['parameters']={**nested,**flat}
                for key in flat:del action[key]
                notes.append(dict(lossless_parameter_packaging=list(flat)))
        if action.get('parameters')=={} and action.get('kind') not in ('layer_settings','snap_settings'):
            del action['parameters'];notes.append('removed unused empty parameters member')
        refs=[]
        for raw in action.get('evidence',[]):
            if not isinstance(raw,str):raise ValueError('evidence reference must be a string')
            if raw in valid_ids:refs.append(raw);continue
            root=raw.split('.',1)[0].split(' ',1)[0]
            if root in {'geometry','layers','quality','fidelity','physics'} and root in valid_ids:
                refs.append(root);notes.append(dict(original=raw,reference=root));continue
            found=[x for x in valid_ids if raw.startswith(x+' ') or raw.startswith(x+',')]
            if found:refs.append(max(found,key=len));continue
            if re.search(r'(?:layer_shortfall|fidelity_loss|\.vt[pku]):\d+',raw):
                raise ValueError('unresolved spatial evidence ID: '+raw)
            notes.append(dict(explanatory_note=raw,verified_reference=False))
        if not refs:raise ValueError('action has no verified evidence reference')
        action['evidence']=list(dict.fromkeys(refs))
    return result,notes


def bounded_patch(target,parameters,schema):
    if not isinstance(parameters,dict) or not parameters or set(parameters)-schema.keys():
        raise ValueError('unknown or empty parameter patch')
    for name,value in parameters.items():
        bounds=schema[name];original=getattr(target,name)
        if isinstance(original,str) or isinstance(original,bool):
            if type(value) is not type(original) or value not in bounds:raise ValueError('invalid categorical parameter '+name)
        else:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not bounds[0]<=value<=bounds[1]:
                raise ValueError('parameter outside certified range: '+name)
            if isinstance(original,int) and int(value)!=value:raise ValueError('integer parameter required: '+name)
        setattr(target,name,int(value) if isinstance(original,int) and not isinstance(original,bool) else value)


def rans_target(length, speed=30.0, nu=1.5e-5, yplus=50.0, layers=8):
    if min(length, speed, nu, yplus) <= 0:
        raise ValueError("positive physical flow inputs required")
    re = speed * length / nu
    cf = 0.074 / max(re, 1.0) ** 0.2
    utau = speed * math.sqrt(cf / 2)
    # y+ is evaluated at the first CELL CENTRE, not at the layer's outer face.
    first = 2 * yplus * nu / utau
    ratio = 1.2
    total = first * (ratio ** layers - 1) / (ratio - 1)
    return dict(speed=speed, nu=nu, reynolds=re, target_yplus=yplus,
                estimated_utau=utau, first_layer_height=first,
                layers=layers, expansion_ratio=ratio, stack_height=total,
                estimated_boundary_layer=0.37 * length / max(re, 1) ** 0.2,
                method="smooth turbulent flat-plate average-Cf estimate",
                limitation="a planning surrogate; actual y+ needs a flow field")


def clusters(points, radius, max_clusters=8):
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if not len(points):
        return []
    points = points[::max(1, len(points)//2048)][:2048]
    pairs = cKDTree(points).query_pairs(radius, output_type="ndarray")
    if len(pairs):
        rows = np.r_[pairs[:, 0], pairs[:, 1]]
        cols = np.r_[pairs[:, 1], pairs[:, 0]]
        graph = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(points), len(points)))
        _, labels = connected_components(graph, directed=False)
    else:
        labels = np.arange(len(points))
    ids, counts = np.unique(labels, return_counts=True)
    order = ids[np.argsort(-counts)][:max_clusters]
    return [points[labels == i] for i in order]


def background_size(spec, geom):
    return geom.longest / spec.domain.base_cells


def finest_size(spec, geom):
    return background_size(spec, geom) / 2 ** spec.surface.level_max


def forecast(spec, geom):
    base = background_size(spec, geom)
    ext = geom.mesh.extents + np.array([spec.domain.padding_upstream + spec.domain.padding_downstream,
                                        2*spec.domain.padding_side,
                                        spec.domain.padding_down + spec.domain.padding_up]) * geom.diagonal
    background = float(np.prod(np.ceil(ext/base)))
    area = geom.mesh.area
    near = 0.0
    prev = 0.0
    for band in spec.distance_levels:
        cell = base / 2 ** band.level
        near += area * max(band.distance-prev, cell) / cell ** 3
        prev = band.distance
    if not spec.distance_levels:
        near = 2 * area / finest_size(spec, geom) ** 2
    regions = sum(float(np.prod(np.asarray(r.max)-r.min)) /
                  (base / 2**(r.gap_level[2] if r.gap_level else r.levels[0].level))**3 for r in spec.regions if r.shape == "box")
    layers = spec.layers.n_surface_layers * area / finest_size(spec, geom)**2 if spec.layers.enabled else 0
    gap_extra_layers=0.
    for region in spec.regions:
        if region.gap_level and spec.layers.enabled:
            triangles=geom.mesh.triangles
            intersect=np.all(triangles.max(axis=1)>=region.min,axis=1)&np.all(triangles.min(axis=1)<=region.max,axis=1)
            local_area=float(geom.mesh.area_faces[intersect].sum())
            gap_h=base/2**region.gap_level[2]
            gap_extra_layers+=spec.layers.n_surface_layers*local_area*max(0.,1/gap_h**2-1/finest_size(spec,geom)**2)
    return dict(background=background, near=near, region_upper_bound=regions,
                layers=layers,gap_extra_layers=gap_extra_layers, total=1.5*(background+near+regions+layers+gap_extra_layers),
                calibration="unvalidated conservative geometry estimate; actual count is a hard acceptance gate")


def shells(spec, geom):
    h = finest_size(spec, geom)
    # Distances are PHYSICAL LENGTHS. Never export raw cell-count multiples.
    spec.distance_levels = [DistanceLevel(2*h, spec.surface.level_max),
                            DistanceLevel(6*h, max(0, spec.surface.level_max-1))]


def retarget_shells(spec, geom):
    """Keep physical normal support when a later action changes surface level."""
    previous=[x.distance for x in spec.distance_levels]
    shells(spec,geom)
    if len(previous)==2:
        spec.distance_levels[0].distance=max(previous[0],spec.distance_levels[0].distance)
        spec.distance_levels[1].distance=max(previous[1],spec.distance_levels[1].distance,
                                            spec.distance_levels[0].distance+finest_size(spec,geom))


def initial_plan(geom, budget=2_000_000, base_cells=8, flow=None, with_layers=True,flow_length=None):
    feature = np.minimum(geom.solid_half_thickness, geom.fluid_gap*0.5)
    p25 = float(np.percentile(feature[np.isfinite(feature)], 25))
    target = min(geom.longest / 40, p25 / 2)
    base = geom.longest/base_cells
    level = max(1, int(math.ceil(math.log2(base/target))))
    if level > 9:
        raise ValueError("geometry requires surface level >9; increase base resolution or budget explicitly")
    if flow_length is not None and (not math.isfinite(flow_length) or flow_length<=0):
        raise ValueError('positive finite flow characteristic length required')
    physics = rans_target(geom.longest if flow_length is None else flow_length, **(flow or {}))
    spec = MeshSpec(
        surface=SurfaceRefinement(level_min=level, level_max=level),
        domain=DomainSpec(mode="box", base_cells=base_cells, padding_upstream=1.5,
                          padding_downstream=4.0, padding_up=1.5, padding_down=1.5, padding_side=1.5),
        features=FeatureSpec(enabled=True, level=level, included_angle=150),
        snap=SnapSpec(n_solve_iter=40, n_relax_iter=5, n_feature_snap_iter=10),
        layers=LayerSpec(enabled=with_layers, n_surface_layers=physics['layers'],
                         expansion_ratio=physics['expansion_ratio'],
                         first_layer_thickness=physics['first_layer_height'],
                         min_thickness=physics['first_layer_height']*0.1),
        max_global_cells=budget, max_local_cells=budget,
        n_cells_between_levels=3, allow_free_standing_zone_faces=False)
    # Exterior seed deliberately lies outside the body bbox and inside the domain.
    # Generate to the independent checker's interpolation-weight requirement.
    spec.quality.min_face_weight=0.05
    spec.location_in_mesh = list(geom.mesh.bounds[0] - 0.5*geom.diagonal)
    shells(spec, geom)
    h = finest_size(spec, geom)
    small = geom.points[np.isfinite(feature) & (feature < 1.5*h)]
    for i, pts in enumerate(clusters(small, 3*h, 6)):
        if len(pts) < 5:
            continue
        f = geom.local_feature(pts)
        local = float(np.percentile(f[np.isfinite(f)], 20))
        wanted = min(level+2, int(math.ceil(math.log2(base/(local/2)))))
        if wanted <= level:
            continue
        pad = 2*h
        spec.regions.append(RefinementRegion(name=f"feature_{i}", shape="box", mode="inside",
                            min=(pts.min(axis=0)-pad).tolist(), max=(pts.max(axis=0)+pad).tolist(),
                            levels=[DistanceLevel(1, wanted)],
                            why="sampled sub-grid feature cluster; no semantic part labels"))
    return spec, physics


def certify(spec, geom, budget,resource_calibration=None):
    reasons = []
    if len({r.name for r in spec.regions})!=len(spec.regions):reasons.append('duplicate refinement region names')
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',r.name) for r in spec.regions):reasons.append('invalid refinement region identifier')
    if any(lv.level>min(9,spec.surface.level_max+4) for r in spec.regions for lv in r.levels):reasons.append('local region exceeds global surface level +4 or level9')
    if any(r.gap_level and r.gap_level[2]>spec.surface.level_max+2 for r in spec.regions):reasons.append('gap region exceeds global surface level +2')
    try:
        spec.validate()
    except ValueError as e:
        reasons.append(str(e))
    h = finest_size(spec, geom)
    base = background_size(spec, geom)
    feature = np.minimum(geom.solid_half_thickness, geom.fluid_gap*0.5)
    local_cell = np.full(len(feature), h)
    for region in spec.regions:
        if region.shape == "box" and region.mode == "inside":
            lo, hi = np.asarray(region.min), np.asarray(region.max)
            mask = np.all((geom.points >= lo) & (geom.points <= hi), axis=1)
            local_cell[mask] = np.minimum(local_cell[mask], base / 2**region.levels[0].level)
    finite = np.isfinite(feature)
    unresolved = float(np.mean(feature[finite]/local_cell[finite] < 1.5))
    if unresolved > 0.10:
        reasons.append("more than 10% sampled surface has fewer than 3 cells across full feature")
    if len(spec.distance_levels) and any(a.distance >= b.distance or a.level < b.level
                                        for a,b in zip(spec.distance_levels, spec.distance_levels[1:])):
        reasons.append("distance shells must increase in physical distance and decrease in level")
    if any(x.distance <= 0 or not math.isfinite(x.distance) for x in spec.distance_levels):
        reasons.append("distance shell length must be finite and positive")
    from .resource_model import adjusted_forecast
    projected = adjusted_forecast(forecast(spec, geom),resource_calibration)
    if projected['total'] > budget:
        reasons.append("projected cells exceed declared budget; precision was not silently relaxed")
    if spec.max_global_cells != budget:
        reasons.append("native maxGlobalCells must equal user budget")
    if projected['background'] > min(1_500_000, budget*0.4):
        reasons.append("background mesh exceeds 40% of budget")
    return dict(ok=not reasons, reasons=reasons, finest=h,
                unresolved_feature_fraction=unresolved, forecast=projected)


def apply_actions(spec, actions, geom, budget,physics_evidence=None,physics_reference=None,plan_history=None,scenario=None,spatial_evidence=None,resource_calibration=None):
    """Bounded public action schema; no raw Dict editing or quality relaxation."""
    candidate = MeshSpec.from_dict(spec.to_dict())
    if not isinstance(actions, list) or not 1 <= len(actions) <= 4:
        raise ValueError("advisor must return 1..4 bounded actions")
    from .targets import resolve_cluster_actions
    actions=resolve_cluster_actions(actions,spatial_evidence,finest_size(spec,geom))
    bands=None
    for position,action in enumerate(actions):
        kind = action.get('kind')
        permitted={'kind','why','evidence'}|({'min','max','level'} if kind=='local_refine' else {'min','max','minimum_cells','start_level','max_level'} if kind=='gap_refine' else {'name','min','max','level'} if kind in ('update_region','flow_refine') else {'name'} if kind=='remove_region' else {'plan_id'} if kind=='restore_plan' else {'parameters'} if kind in ('layer_settings','snap_settings','resolution_settings','refinement_bands','generation_quality') else {'scale'} if kind=='wall_height' else set())
        if kind=='local_refine':permitted.add('compiled_measured_target')
        if set(action)-permitted:
            raise ValueError(f'unexpected fields for {kind}; use local_refine for a coordinate box')
        if not action.get('why') or not action.get('evidence'):
            raise ValueError("every action requires why and evidence references")
        if kind=='gap_refine':
            lo=np.asarray(action['min'],float);hi=np.asarray(action['max'],float)
            if lo.shape!=(3,) or hi.shape!=(3,) or not np.isfinite([lo,hi]).all() or np.any(hi<=lo):raise ValueError('invalid gap refinement box')
            labels=[action[k] for k in ('minimum_cells','start_level','max_level')]
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or int(v)!=v for v in labels):raise ValueError('gap refinement labels must be integers')
            labels=list(map(int,labels));cells,start,end=labels
            if not 3<=cells<=8 or not 0<=start<=end<=candidate.surface.level_max+2:raise ValueError('gap refinement needs 3..8 cells, ordered levels, maximum within global+2')
            if end<=candidate.surface.level_max:raise ValueError('gap refinement maximum must add resolution above the global surface level')
            for old in candidate.regions:
                if old.shape=='box' and old.gap_level and np.all(lo>=old.min) and np.all(hi<=old.max) and old.gap_level[0]>=cells and old.gap_level[1]<=start and old.gap_level[2]>=end:
                    raise ValueError('gap region already covered by equal or stronger gap refinement')
            number=0;names={r.name for r in candidate.regions}
            while f'gap_{number}' in names:number+=1
            candidate.regions.append(RefinementRegion(name=f'gap_{number}',shape='box',mode='inside',levels=[DistanceLevel(1,0)],min=lo.tolist(),max=hi.tolist(),gap_level=labels,why=action['why']))
        elif kind=='flow_refine':
            from .scenario import flow_region
            region=flow_region(candidate,action,geom,scenario)
            candidate.regions=[r for r in candidate.regions if r.name!=region.name]+[region]
        elif kind=='restore_plan':
            if position!=0:raise ValueError('restore_plan must be the first and only restore action')
            anchor=next((r for r in plan_history or [] if plan_id(r['spec'])==action['plan_id']),None)
            if anchor is None or not eligible(anchor,budget):raise ValueError('restore requires a measured native-quality and geometry valid anchor')
            candidate=MeshSpec.from_dict(anchor['spec'])
        elif kind=='remove_region':
            match=[r for r in candidate.regions if r.name==action['name']]
            if len(match)!=1:raise ValueError('unknown or ambiguous refinement region')
            candidate.regions.remove(match[0])
        elif kind=='wall_height':
            probe=physics_evidence or {};scale=action.get('scale')
            if not (probe.get('numerical_sanity',{}).get('accepted') and probe.get('field_sanity',{}).get('accepted') and probe.get('actual_yplus_distribution',{}).get('available')):
                raise ValueError('wall-height calibration requires a numerically sane measured flow field')
            if physics_reference is None or isinstance(scale,bool) or not isinstance(scale,(int,float)) or not math.isfinite(scale) or not .5<=scale<=2:
                raise ValueError('wall height must be 0.5..2 times the original physical estimate')
            if 'physics' not in action['evidence']:raise ValueError('wall height must cite physics')
            reference=physics_reference['first_layer_height'];ratio=candidate.layers.min_thickness/candidate.layers.first_layer_thickness
            candidate.layers.first_layer_thickness=reference*scale
            candidate.layers.min_thickness=candidate.layers.first_layer_thickness*ratio
        elif kind=='resolution_settings':
            parameters=action['parameters']
            if not isinstance(parameters,dict) or not parameters or set(parameters)-RESOLUTION_PARAMETERS.keys():raise ValueError('unknown resolution parameters')
            for key,value in parameters.items():
                lo,hi=RESOLUTION_PARAMETERS[key]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or int(value)!=value or not lo<=value<=hi:raise ValueError('invalid resolution setting')
                if key=='base_cells':candidate.domain.base_cells=int(value)
                else:candidate.surface.level_min=candidate.surface.level_max=candidate.features.level=int(value)
            retarget_shells(candidate,geom)
        elif kind=='refinement_bands':
            if bands is not None:raise ValueError('only one refinement band action per proposal')
            bands=action['parameters']
            if not isinstance(bands,dict) or set(bands)!=set(BAND_PARAMETERS):raise ValueError('both physical band distances required')
            for key,value in bands.items():
                lo,hi=BAND_PARAMETERS[key]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('invalid physical band distance')
        elif kind=='generation_quality':
            parameters=action['parameters']
            if not isinstance(parameters,dict):raise ValueError('generation quality requires parameters')
            for name,value in parameters.items():
                if name not in GENERATION_QUALITY_PARAMETERS:raise ValueError('unknown generation quality field')
                previous=getattr(candidate.quality,name)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('finite numerical quality value required')
                if (name.startswith('max_') and value>previous) or (name.startswith('min_') and value<previous):
                    raise ValueError('generation quality may only tighten; independent acceptance cannot be changed')
            bounded_patch(candidate.quality,parameters,GENERATION_QUALITY_PARAMETERS)
        elif kind in ('layer_settings','snap_settings'):
            bounded_patch(candidate.layers if kind=='layer_settings' else candidate.snap,
                          action['parameters'],LAYER_PARAMETERS if kind=='layer_settings' else SNAP_PARAMETERS)
        elif kind in ('local_refine','update_region'):
            lo, hi = np.asarray(action['min'],dtype=float), np.asarray(action['max'],dtype=float)
            if lo.shape != (3,) or hi.shape != (3,) or not np.isfinite([lo,hi]).all() or np.any(hi<=lo):
                raise ValueError("invalid local box")
            if np.any(hi < geom.mesh.bounds[0]-geom.diagonal) or np.any(lo > geom.mesh.bounds[1]+geom.diagonal):
                raise ValueError("local repair does not intersect body neighbourhood")
            value=action.get('level',candidate.surface.level_max+1)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or int(value)!=value:raise ValueError('local refinement level must be an integer')
            level = int(value)
            extra=4 if action.get('compiled_measured_target') else 2
            if level < candidate.surface.level_max or level > min(9,candidate.surface.level_max+extra):
                raise ValueError('local refinement exceeds surface+'+str(extra)+' or level9; only exact measured targets may use +4')
            if kind=='local_refine':
                if level==candidate.surface.level_min:raise ValueError('local refinement does not add resolution above existing global minimum')
                for old in candidate.regions:
                    if old.shape=='box' and old.mode=='inside' and not old.gap_level and np.all(lo>=old.min) and np.all(hi<=old.max) and old.levels[0].level>=level:
                        raise ValueError('local region already covered by equal or finer existing refinement; change the mechanism or level')
            if kind=='update_region':
                match=[(i,r) for i,r in enumerate(candidate.regions) if r.name==action['name']]
                if len(match)!=1 or match[0][1].shape!='box' or match[0][1].mode!='inside':raise ValueError('update requires an existing inside box')
                index,old=match[0];name=old.name
            else:
                names={r.name for r in candidate.regions};index=len(candidate.regions);number=0
                while f'repair_{number}' in names:number+=1
                name=f'repair_{number}'
            replacement=RefinementRegion(name=name,shape='box',mode='inside',min=lo.tolist(),max=hi.tolist(),levels=[DistanceLevel(1,level)],why=action['why'])
            if kind=='update_region':replacement.gap_level=old.gap_level;replacement.gap_mode=old.gap_mode
            if kind=='update_region':candidate.regions[index]=replacement
            else:candidate.regions.append(replacement)
        elif kind == 'snap_smooth':
            candidate.snap.n_solve_iter = max(candidate.snap.n_solve_iter,min(80,candidate.snap.n_solve_iter+15))
            candidate.snap.n_relax_iter = max(candidate.snap.n_relax_iter,min(12,candidate.snap.n_relax_iter+2))
        elif kind == 'transition':
            candidate.n_cells_between_levels = min(5,candidate.n_cells_between_levels+1)
        elif kind == 'surface_refine':
            candidate.surface.level_max += 1
            candidate.surface.level_min = candidate.surface.level_max
            candidate.features.level = candidate.surface.level_max
            retarget_shells(candidate,geom)
        elif kind == 'layer_smooth':
            candidate.layers.n_smooth_normals = max(candidate.layers.n_smooth_normals,min(8,candidate.layers.n_smooth_normals+2))
            candidate.layers.n_smooth_thickness = max(candidate.layers.n_smooth_thickness,min(20,candidate.layers.n_smooth_thickness+5))
            candidate.layers.n_relax_iter = max(candidate.layers.n_relax_iter,min(10,candidate.layers.n_relax_iter+2))
            candidate.layers.n_layer_iter = max(candidate.layers.n_layer_iter,min(80,candidate.layers.n_layer_iter+15))
        elif kind == 'layer_trim':
            # First height remains physical; never remove all layers to claim RANS readiness.
            candidate.layers.n_surface_layers = max(5,candidate.layers.n_surface_layers-1)
        else:
            raise ValueError(f"unsupported action {kind}")
    if [a['kind'] for a in actions].count('surface_refine')>1:
        raise ValueError('a proposal can raise the global surface level only once')
    if bands is not None:
        inner,outer=bands['inner_distance'],bands['outer_distance']
        if not 2*finest_size(candidate,geom)<=inner<outer<=geom.diagonal:
            raise ValueError('physical bands require 2 refined cells <= inner < outer <= body diagonal')
        candidate.distance_levels=[DistanceLevel(inner,candidate.surface.level_max),
                                   DistanceLevel(outer,max(0,candidate.surface.level_max-1))]
    cert = certify(candidate,geom,budget,resource_calibration)
    if not cert['ok']:
        raise ValueError("proposed actions failed certification: "+'; '.join(cert['reasons'])+
            f'; planning estimated cells={cert["forecast"]["total"]:.0f}, declared cap={budget}, candidate base_cells={candidate.domain.base_cells}, surface_level={candidate.surface.level_max}, global surface width={finest_size(candidate,geom):.9g} m')
    if scenario:
        from .scenario import plan_screen
        if not plan_screen(candidate,geom,scenario)['accepted']:
            raise ValueError('proposed actions failed immutable off-body scenario coverage')
    return candidate


def preflight_replan(spec,geom,budget,attempts=3):
    """Bounded geometric planning, before ANY paid meshing/model round."""
    trace=[]
    for attempt in range(attempts+1):
        cert=certify(spec,geom,budget)
        trace.append(dict(attempt=attempt,certification=cert,spec=spec.to_dict()))
        if cert['ok'] or attempt==attempts:
            return spec,trace
        if any('budget' in reason or 'background' in reason for reason in cert['reasons']):
            return spec,trace
        h=finest_size(spec,geom);base=background_size(spec,geom)
        feature=np.minimum(geom.solid_half_thickness,geom.fluid_gap*.5)
        local=np.full(len(feature),h)
        for r in spec.regions:
            if r.shape=='box':
                mask=np.all((geom.points>=r.min)&(geom.points<=r.max),axis=1)
                local[mask]=np.minimum(local[mask],base/2**r.levels[0].level)
        bad=geom.points[np.isfinite(feature)&(feature/local<1.5)]
        candidate=MeshSpec.from_dict(spec.to_dict())
        # Scattered small features matter even when represented by one measured sample.
        # Dropping singleton clusters systematically erases thin, spatially dispersed detail.
        for pts in clusters(bad,2*h,64):
            level=min(9,spec.surface.level_max+min(2,attempt+1))
            candidate.regions.append(RefinementRegion(name=f'preflight_{len(candidate.regions)}',
                shape='box',mode='inside',min=(pts.min(axis=0)-h).tolist(),
                max=(pts.max(axis=0)+h).tolist(),levels=[DistanceLevel(1,level)],
                why='remaining unresolved measured features; bounded preflight planning'))
        if candidate.to_dict()==spec.to_dict(): return spec,trace
        spec=candidate
    return spec,trace


def deterministic_actions(evidence, spec, geom):
    quality=evidence.get('quality') or {}
    if not quality.get('accepted'):
        critical=[d for d in evidence.get('spatial',[]) if any(s in d.get('metric','').lower()
                    for s in ('zerovolume','negative','illegal','meshquality','nonortho','skew','highaspect'))]
        if critical:
            d=critical[0]
            return [dict(kind='local_refine',min=d['min'],max=d['max'],level=spec.surface.level_max+1,
                         why='local native FV quality failure; repair before layer optimisation',evidence=[d['id']]),
                    dict(kind='snap_smooth',why='improve snapped cells at native failed locations',evidence=[d['id']])]
    layers=evidence.get('layers') or {}
    if layers.get('available') and not layers.get('accepted'):
        short=[d for d in evidence.get('spatial',[]) if d.get('cause')=='layer_shortfall']
        if short:
            d=short[0]
            return [dict(kind='local_refine',min=d['min'],max=d['max'],
                         level=spec.surface.level_max+1,
                         why='actual layer deficit concentrated in measured boundary faces',evidence=[d['id']]),
                    dict(kind='layer_trim',why='shorten total stack while keeping first height and five layers',evidence=['layers'])]
        return [dict(kind='layer_trim' if spec.layers.n_surface_layers>5 else 'layer_smooth',
                     why='actual physical-layer coverage insufficient',evidence=['layers'])]
    diagnoses = evidence.get('spatial',[])
    for item in diagnoses:
        if item.get('cause') in ('unresolved_gap','underresolved_feature','fidelity_loss'):
            return [dict(kind='local_refine',min=item['min'],max=item['max'],
                         level=spec.surface.level_max+1,why=item['cause'],evidence=[item['id']])]
        if item.get('cause') == 'snap_artifact':
            return [dict(kind='snap_smooth',why='near-wall bad cells with ample local room',evidence=[item['id']])]
        if item.get('cause') == 'transition':
            return [dict(kind='transition',why='bad cells in refinement transition',evidence=[item['id']])]
    layers=evidence.get('layers') or {}
    if layers.get('coverage',0) < .90:
        return [dict(kind='layer_smooth',why='insufficient physical layer coverage',evidence=['layers'])]
    return [dict(kind='snap_smooth',why='failed quality without a reliable local cluster',evidence=['quality'])]
