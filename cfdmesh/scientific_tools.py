"""Read-only scientific queries and proposal previews, executed on the compute node."""
from pathlib import Path
import numpy as np
from .planning import background_size,finest_size,apply_actions,certify,LAYER_PARAMETERS,SNAP_PARAMETERS,RESOLUTION_PARAMETERS,BAND_PARAMETERS,GENERATION_QUALITY_PARAMETERS,normalise_actions
from .verify import boundary_scalar,obj_face_geometry
from .candidates import plan_id,catalog

HELP={
 'gap_support':{'meaning':'gap_refine {min,max,minimum_cells,start_level,max_level} declares native gapLevel in an anonymous coordinate box, gapMode outside, not a semantic part. minimum_cells 3..8; max_level within global+2. The box has dummy level0; only native detected gaps trigger extra refinement. Budget forecast counts the entire box at max_level plus additional possible local wall layers. gap refinement does not create physical extrusion room. Compare exact layer stack with measured outward normal hits; two opposing equal stacks exceeding a ray hit is a geometric warning, not a native medial proof. No finite hit is unknown. Source normals must remain consistently outward. Native outside mode can discard cells by surface orientation; final geometry fidelity must still pass. No changing/deleting/healing source geometry is authorised.',
   'source':'installed v2412 refinementSurfaces.C gapLevel/gapMode validation and tutorials/mesh/snappyHexMesh/gap_detection; https://api.openfoam.com/2412/refinementSurfaces_8C_source.html'},
 'surface_topology':{'meaning':'n_face_split_interval=-1 disables splitting; a positive interval no greater than n_feature_snap_iter enables feature-aligned native face splitting. Half the feature snap iterations is a documented starting hypothesis, not a guarantee. avoid_diagonal reduces diagonal attraction/collapse. layer_termination_angle and detect_extrusion_island change truncation near partially extruded neighbours; -180 attempts corner extrusion but may create bad cells. Validate topology and quality, not just coverage. generation_quality only TIGHTENS construction constraints; acceptance is fixed. Default generated boundary skew is4 to match the global checkMesh gate. min_tet_quality can impose a safety margin on nearly degenerate face decompositions. Do not confuse surface n-gons needing a different observer with bad volume cells.',
   'triangle_normal_coherence':'min_triangle_twist defaults -1 (disabled). Nonnegative values tighten consecutive face-centre triangle-normal alignment; this differs from min_twist, tetrahedral quality and planar warp. The native user guide lists >0 for Fluent compatibility, not for matching Fluent layer coverage. It may suppress extrusion and does not prove global surface closure/self-intersection freedom.',
   'source':'https://doc.openfoam.com/2306/tools/pre-processing/mesh/generation/snappyhexmesh/snapping/; https://www.openfoam.com/news/main-news/openfoam-v3.0/meshing; https://www.openfoam.com/documentation/user-guide/4-mesh-generation-and-conversion/4.4-mesh-generation-with-the-snappyhexmesh-utility'},
 'reversible_plans':{'meaning':'restore_plan must be FIRST and refer to a measured native-quality/geometry valid plan_id in candidate_catalog. It restores the whole spec, then applies the remaining interventions under unchanged gates. remove_region deletes one named region; update_region replaces an existing inside box. Needed feature refinement cannot be removed if final joint certification fails. A restored unchanged tested spec will not consume another native attempt. Candidate anchors are provisional, never RANS certificates.'},
 'layer_corners':{'meaning':'featureAngle is a layer extrusion/shrinking angle, not the surface feature extraction includedAngle. When angle between surfaces exceeds featureAngle, layer extrusion near the feature is suppressed. Sharp corners may need a different corner treatment, not more surface cells.',
   'source':'https://doc.openfoam.com/2306/tools/pre-processing/mesh/generation/snappyhexmesh/layers/'},
 'layer_shrinker':{'meaning':'displacementMedialAxis is default. displacementMotionSolver with displacementLaplacian and quadratic inverseDistance diffusivity smooths mesh shrinking. Harness writes compatible fvSolution cellDisplacement GAMG and fvSchemes. It can reduce distortion but is not a success guarantee.',
   'v2412_native_semantics':'snappyLayerDriver skips handleWarpedFaces/maxFaceThicknessRatio when any patch uses relativeSizes false (this harness uses absolute physical first heights). It is NOT a cap on first-layer height divided by face size. medialAxisMeshMover tests (thickness/medialDist) times the extrusion-to-medial direction dot product, then halves thickness toward minThickness when above maxThicknessToMedialRatio; it is not a direct cap thickness=ratio*distance.',
   'quantity_types':'maxThicknessToMedialRatio uses the native FLUID mesh medial distance. Solid normal half-thickness or tube radius is not that field. Zero finite outward-ray gaps does not prove absent gaps.',
   'outer_iterations':'Installed v2412 snappyLayerDriver partitions the requested layers across nOuterIter passes, growing slices from outer to inner layers. It is not a generic retry count for the same final layer stack. A higher number can change layer construction and must pass independent final quality checks.',
   'shrinker_specific_controls':'Installed v2412 medialAxisMeshMover.C reads nSmoothNormals, maxThicknessToMedialRatio, minMedialAxisAngle, layerTerminationAngle and detectExtrusionIsland. They are not active under displacementMotionSolver. Do not propose them as a mechanism for improving that shrinker. Parameter presence in a Dict does not prove consumption. layerTerminationAngle default is half featureAngle; detectExtrusionIsland default false, within the medial-axis mover.',
   'n_grow':'Installed snappyLayerDriver calls growNoExtrusion nGrow times: it propagates NOEXTRUDE to adjacent patch points and zeros their displacement/layer count. Increasing nGrow grows the NON-EXTRUSION region; it does NOT grow layers onto previously unextruded faces. It may make transitions safer while reducing coverage. Choose it only with that tradeoff in mind.',
   'source':'OpenFOAM v2412 installed aerofoilNACA0012_directionalRefinement tutorial; https://api.openfoam.com/2306/classFoam_1_1displacementMotionSolverMeshMover.html'},
 'layers_physics':{'meaning':'Speed, viscosity, target y+ and acceptance thresholds are immutable. First height starts from a flat-plate estimate. wall_height can set 0.5..2 times that ORIGINAL estimate only after an actual numerically sane flow probe. Use measured wall-shear/y+ distribution, never a divergent field. Changing expansion_ratio or n_surface_layers changes stack thickness; inference from actual thickness uses the proposed ratio. At least 5 actual layers over 90% body area is still required. Do not remove hard regions to pass.',
   'source':'https://api.openfoam.com/2312/layerParameters_8C_source.html'},
 'refinement':{'meaning':'Distance-shell lengths and local box coordinates are metres. Background h=L/base_cells; level-l h=background/2^l. refinement_bands sets inner_distance at the global surface level and outer_distance at one level lower; require 2h <= inner < outer <= body diagonal. Compare normal support depth with requested layer stack and transition location. Deeper bands may provide shrink space without raising tangential resolution, but add cells and do not guarantee valid layers. Refinement does not cure every extrusion defect. A local box adds volume cells and may create transition defects.',
   'source':'https://www.openfoam.com/documentation/user-guide/4-mesh-generation-and-conversion/4.4-mesh-generation-with-the-snappyhexmesh-utility'}}

TOOLS=[
 {'type':'function','function':{'name':'inspect_scenario','description':'Read immutable flow intent, Reynolds regime, hypothesised wake/shear/vortex requirements and configured off-body coverage. These are NOT observed flow features.',
   'parameters':{'type':'object','properties':{},'additionalProperties':False}}},
 {'type':'function','function':{'name':'inspect_plan','description':'Read a measured plan anchor from the trusted candidate catalog; includes full typed settings and outcome, no meshing.',
   'parameters':{'type':'object','properties':{'plan_id':{'type':'string'}},'required':['plan_id'],'additionalProperties':False}}},
 {'type':'function','function':{'name':'query_region','description':'Measure whole-body dihedral angles, local sampled thickness/gaps/normals and actual layers in a coordinate box, or for the entire body when bounds omitted. Coordinates in metres.',
   'parameters':{'type':'object','properties':{'min':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3},'max':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3}},'additionalProperties':False}}},
 {'type':'function','function':{'name':'inspect_cluster','description':'Retrieve a diagnostic cluster by its evidence ID, including a local region measurement.',
   'parameters':{'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False}}},
 {'type':'function','function':{'name':'preview_actions','description':'Validate a proposed action bundle without running meshing. Returns exact physical scales, parameter differences and a conservative cell forecast. Does not spend a mesh round.',
   'parameters':{'type':'object','properties':{'actions':{'type':'array','items':{'type':'object'},'minItems':1,'maxItems':4}},'required':['actions'],'additionalProperties':False}}},
 {'type':'function','function':{'name':'openfoam_reference','description':'Read version-specific validated parameter semantics and available layer/snap parameter schema.',
   'parameters':{'type':'object','properties':{'topic':{'type':'string','enum':list(HELP)}},'required':['topic'],'additionalProperties':False}}}]


def plan_tool(evidence):
    ids=['geometry'] if evidence.get('stage','').startswith('before') else ['geometry','quality','layers','fidelity','physics']+[d['id'] for d in evidence.get('spatial',[])]
    from .scenario import evidence_ids
    ids.extend(sorted(evidence_ids(evidence.get('scenario'))))
    common=dict(kind={'type':'string'},why={'type':'string'},evidence={'type':'array','items':{'type':'string','enum':ids},'minItems':1})
    ids.extend(p['plan_id'] for p in evidence.get('candidate_catalog',[]))
    branches=[]
    for kind,schema in [('layer_settings',LAYER_PARAMETERS),('snap_settings',SNAP_PARAMETERS),('resolution_settings',RESOLUTION_PARAMETERS),('refinement_bands',BAND_PARAMETERS),('generation_quality',GENERATION_QUALITY_PARAMETERS)]:
        params={}
        for key,bounds in schema.items():
            if isinstance(bounds[0],str):params[key]=dict(type='string',enum=list(bounds))
            elif isinstance(bounds[0],bool):params[key]=dict(type='boolean')
            else:
                integer=key.startswith('n_') or key in ('surface_level','base_cells')
                params[key]=dict(type='integer' if integer else 'number',minimum=bounds[0],maximum=bounds[1])
            if key=='n_face_split_interval':params[key]=dict(anyOf=[dict(type='integer',enum=[-1]),dict(type='integer',minimum=1,maximum=30)])
        props={**common,'kind':dict(type='string',enum=[kind]),'parameters':dict(type='object',properties=params,additionalProperties=False,minProperties=1)}
        if kind=='refinement_bands':props['parameters']['required']=list(BAND_PARAMETERS)
        branches.append(dict(type='object',properties=props,required=['kind','why','evidence','parameters'],additionalProperties=False))
    coords=dict(type='array',items=dict(type='number'),minItems=3,maxItems=3)
    spatial_ids=[d['id'] for d in evidence.get('spatial',[])]
    if spatial_ids:
        branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['cluster_refine']),
            'ids':dict(type='array',items=dict(type='string',enum=spatial_ids),minItems=1,maxItems=4,uniqueItems=True),
            'level':dict(type='integer',minimum=1,maximum=9),
            'padding_cells':dict(type='number',minimum=0,maximum=2)},
            required=['kind','why','evidence','ids','level'],additionalProperties=False))
    branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['gap_refine']),
        'min':coords,'max':coords,'minimum_cells':dict(type='integer',minimum=3,maximum=8),
        'start_level':dict(type='integer',minimum=0,maximum=9),'max_level':dict(type='integer',minimum=1,maximum=11)},
        required=['kind','why','evidence','min','max','minimum_cells','start_level','max_level'],additionalProperties=False))
    if evidence.get('scenario'):
        branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['flow_refine']),
            'name':dict(type='string',pattern='^flow_[A-Za-z0-9_]+$'),'min':coords,'max':coords,
            'level':dict(type='integer',minimum=0,maximum=9)},
            required=['kind','why','evidence','name','min','max','level'],additionalProperties=False))
    branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['local_refine']),
        'min':coords,'max':coords,'level':dict(type='integer')},required=['kind','why','evidence','min','max','level'],additionalProperties=False))
    branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['update_region']),
        'name':dict(type='string'),'min':coords,'max':coords,'level':dict(type='integer')},required=['kind','why','evidence','name','min','max','level'],additionalProperties=False))
    branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['remove_region']),
        'name':dict(type='string')},required=['kind','why','evidence','name'],additionalProperties=False))
    anchors=[p['plan_id'] for p in evidence.get('candidate_catalog',[]) if p['eligible_for_restore']]
    if anchors:branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['restore_plan']),
        'plan_id':dict(type='string',enum=anchors)},required=['kind','why','evidence','plan_id'],additionalProperties=False))
    branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['surface_refine','transition','layer_smooth','layer_trim','snap_smooth'])},
        required=['kind','why','evidence'],additionalProperties=False))
    branches.append(dict(type='object',properties={**common,'kind':dict(type='string',enum=['wall_height']),
        'scale':dict(type='number',minimum=.5,maximum=2)},required=['kind','why','evidence','scale'],additionalProperties=False))
    return dict(type='function',function=dict(name='propose_mesh_plan',description='Submit the final scientific plan. This is the ONLY final-answer interface. Parameter values must be in parameters, never only in why. Does not execute meshing.',
        parameters=dict(type='object',properties=dict(hypothesis=dict(type='string'),alternatives=dict(type='array',items=dict(type='string')),
            counterevidence=dict(type='array',items=dict(type='string')),expected_change=dict(type='string'),
            disposition=dict(type='string',enum=['repair','stop']),actions=dict(type='array',items=dict(anyOf=branches),maxItems=4)),
            required=['hypothesis','expected_change','actions'],additionalProperties=False)))


def scales(spec,geom):
    l=spec.layers;r=l.expansion_ratio
    from .mechanisms import stack_height,MEDIAL_ONLY_PARAMETERS
    from .scenario import domain_bounds
    bounds=domain_bounds(spec,geom) if spec.domain.mode=='box' else None
    return dict(background_cell_metres=background_size(spec,geom),global_surface_cell_metres=finest_size(spec,geom),
        computational_domain_bounds_metres=[x.tolist() for x in bounds] if bounds is not None else None,
        first_layer_height_metres=l.first_layer_thickness,
        nominal_first_cell_centre_metres=l.first_layer_thickness/2,
        requested_layer_stack_metres=stack_height(l),
        requested_outer_layer_metres=l.first_layer_thickness*r**(l.n_surface_layers-1),
        global_surface_level=spec.surface.level_max,
        physical_refinement_bands=[dict(distance_metres=x.distance,level=x.level) for x in spec.distance_levels],
        iteration_effort_proxy=dict(product=l.n_outer_iter*l.n_layer_iter*l.n_relax_iter,
            limitation='uncalibrated iteration ceiling product, not a runtime forecast; coupled increases can exhaust the stage budget'),
        native_layer_semantics=dict(n_grow='propagates NON-EXTRUSION to neighbours; not a layer fill/growth pass',relative_sizes=l.first_layer_thickness<=0,
          mesh_shrinker=l.mesh_shrinker,
          medial_only_parameters=sorted(MEDIAL_ONLY_PARAMETERS),
          medial_only_parameters_active=l.mesh_shrinker=='displacementMedialAxis',
          max_face_thickness_ratio_active=l.first_layer_thickness<=0,
          max_face_thickness_ratio_meaning='warped-face extrusion check, disabled for absolute heights; not a first-layer/face-size clamp',
          source='installed OpenFOAM v2412 snappyLayerDriver.C handleWarpedFaces guard; medialAxisMeshMover.C and displacementMotionSolverMeshMover.C parameter readers'))


def quantiles(values):
    x=np.asarray(values);x=x[np.isfinite(x)]
    return {f'p{q}':float(np.percentile(x,q)) for q in (5,50,95)} if len(x) else None


def query_region(args,context):
    geom=context['geometry'];spec=context['spec'];p=geom.points
    if bool('min' in args)!=bool('max' in args):raise ValueError('both bounds required')
    lo=np.asarray(args.get('min',geom.mesh.bounds[0]),float);hi=np.asarray(args.get('max',geom.mesh.bounds[1]),float)
    if lo.shape!=(3,) or hi.shape!=(3,) or not np.isfinite([lo,hi]).all() or np.any(hi<=lo):raise ValueError('invalid box')
    selected=np.all((p>=lo)&(p<=hi),axis=1)
    edge_centres=geom.mesh.vertices[geom.mesh.face_adjacency_edges].mean(axis=1)
    edges=np.all((edge_centres>=lo)&(edge_centres<=hi),axis=1)
    angles=np.degrees(geom.mesh.face_adjacency_angles[edges])
    result=dict(box=dict(min=lo.tolist(),max=hi.tolist()),geometry_samples=int(selected.sum()),
        solid_normal_half_thickness_metres=quantiles(geom.solid_half_thickness[selected]),
        fluid_gap_metres=quantiles(geom.fluid_gap[selected]),
        finite_fluid_gap_fraction=float(np.isfinite(geom.fluid_gap[selected]).mean()) if selected.any() else None,
        dihedral_angle_degrees=quantiles(angles),
        fraction_adjacent_edges_above_layer_feature_angle=float(np.mean(angles>spec.layers.feature_angle)) if len(angles) else None,
        edge_count=int(edges.sum()),physical_scales=scales(spec,geom),
        limits='normal-ray and sampled measurements; not a certified medial-axis LFS')
    adjacency=geom.mesh.face_adjacency[edges]
    span=np.linalg.norm(geom.mesh.triangles_center[adjacency[:,0]]-geom.mesh.triangles_center[adjacency[:,1]],axis=1) if len(adjacency) else np.array([])
    result['discrete_normal_rotation_per_metre']=quantiles(np.radians(angles)/np.maximum(span,1e-30))
    result['curvature_limit']='triangle-normal rotation over adjacent centroids; tessellation-dependent proxy, not fitted principal curvature'
    from .mechanisms import region_support
    result['layer_support']=region_support(spec,geom,lo,hi,selected)
    ids=np.flatnonzero(selected);ids=ids[::max(1,len(ids)//128)][:128]
    if len(ids):
        from .geometry import ray_distance
        pts=geom.points[ids];normal=geom.normals[ids];axis=np.eye(3)[np.argmin(np.abs(normal),axis=1)]
        u=np.cross(normal,axis);u/=np.linalg.norm(u,axis=1)[:,None];v=np.cross(normal,u)
        rays=[]
        for tangent in (u,-u,v,-v):
            direction=normal*np.cos(np.pi/6)+tangent*np.sin(np.pi/6)
            rays.append(ray_distance(geom.mesh,pts,direction,1,geom.diagonal))
        gap=np.min(np.vstack([geom.fluid_gap[ids]]+rays),axis=0)
        result['directional_outward_hit_distance']=dict(samples=len(ids),directions=5,cone_degrees=30,
            finite_fraction=float(np.isfinite(gap).mean()),distance_metres=quantiles(gap),
            limitation='five directional samples of outward ray hit length; not native fluid medial distance or a no-gap proof')
    case=context.get('case')
    if case and (Path(case)/'body.obj').exists():
        from .boundary import read_polygons
        vertices,faces=read_polygons(Path(case)/'body.obj')
        native_centres=np.array([vertices[f].mean(axis=0) for f in faces])
        native_mask=np.all((native_centres>=lo)&(native_centres<=hi),axis=1) if args else np.ones(len(faces),dtype=bool)
        selected_faces=np.flatnonzero(native_mask)
        widths=np.array([np.ptp(vertices[faces[i]],axis=0) for i in selected_faces]).reshape(-1,3)
        result['native_boundary_polygons']=dict(faces_in_region=len(selected_faces),
            bbox_span_by_axis_metres={axis:quantiles(widths[:,i]) for i,axis in enumerate('xyz')},
            example_native_face_indices=selected_faces[:16].tolist(),
            limitation='raw native wall polygon bbox spans; not volume-cell sizes, a triangulation certificate or a causal diagnosis')
        from .native_trace import wall_medial_snapshot
        result['native_pre_limit_wall_points']=wall_medial_snapshot(case,lo if args else None,hi if args else None)
        log=Path(case)/'logs/snappyHexMesh.log'
        if log.exists():
            lines=log.read_text(errors='replace').splitlines()
            result['native_layer_mechanism_log']=[x.strip() for x in lines if any(s in x.lower() for s in ('medial','disabled extrusion','extruding','non-extrud','feature angle','thickness too'))][-30:]
        native=list(Path(case).glob('processor*/0/pointMedialDist'))+list(Path(case).glob('0/pointMedialDist'))
        # pointMedialDist is an internal point field; calculated patch values can
        # remain default zero. Never interpret those as wall medial distances.
        result['native_medial_field_artifacts']=dict(files=[str(p.relative_to(case)) for p in native],
            available_for_wall_measurement=False,limitation='pre-layer internal point field; patch values and final mesh indexing are not a validated wall mapping')
        lines=list(Path(case).glob('processor*/thicknessRatioExcludeMedialVec_*.obj'))+list(Path(case).glob('thicknessRatioExcludeMedialVec_*.obj'))
        result['native_thickness_truncation']=truncation_lines(lines,lo if args else np.full(3,-np.inf),hi if args else np.full(3,np.inf))
        result['native_selection_scope']='explicit coordinate box' if args else 'entire native body, including pre-layer points displaced outside source bounding box'
        if not (Path(case)/'0/nSurfaceLayers').exists():
            result['actual_layers']=dict(available=False,reason='no native layer field: this may be a pre-layer snap stage; geometry measurements remain available')
            return result
        areas,centres=obj_face_geometry(Path(case)/'body.obj')
        values,uniform=boundary_scalar(Path(case)/'0/nSurfaceLayers')
        if uniform:values=np.full(len(areas),values[0])
        if len(values)!=len(areas):raise ValueError('native layer faces inconsistent')
        mask=np.all((centres>=lo)&(centres<=hi),axis=1) if args else np.ones(len(centres),dtype=bool)
        a=areas[mask].sum()
        result['actual_layers']=dict(body_area_in_region=float(a),
            coverage_5plus=float(areas[mask&(values>=5)].sum()/a) if a else None,
            area_fraction_by_layers={str(int(k)):float(areas[mask&(values==k)].sum()/a) for k in np.unique(values[mask])} if a else {})
        probe=Path(case)/'flow_probe'
        times=[p for p in probe.glob('*/yPlus') if p.parent.name.replace('.','',1).isdigit()]
        if times:
            field=max(times,key=lambda p:float(p.parent.name));yplus,uniform=boundary_scalar(field)
            if uniform:yplus=np.full(len(areas),yplus[0])
            if len(yplus)!=len(areas):raise ValueError('flow y+ faces inconsistent')
            order=np.argsort(yplus[mask]);v=yplus[mask][order];area=areas[mask][order]
            if len(v) and area.sum()>0:
                cdf=np.cumsum(area)/area.sum()
                result['actual_flow_yplus']=dict(
                    area_weighted_quantiles={f'p{q}':float(v[min(np.searchsorted(cdf,q/100),len(v)-1)]) for q in (5,15,50,85,95)},
                    area_fraction_30_to_300=float(area[(v>=30)&(v<=300)].sum()/area.sum()),
                    numerical_sanity=context['evidence'].get('flow_probe',{}).get('accepted_for_smoke'),
                    limitation='short flow probe; wall shear may change with first height and is not converged')
    return result


def truncation_lines(files,lo,hi):
    """Native shrinker line endpoints carry coordinates without a final-face map."""
    starts=[];lengths=[];errors=[];total=0
    for path in files:
        try:
            vertices=[]
            for line in Path(path).read_text().splitlines():
                items=line.split()
                if items and items[0]=='v':vertices.append([float(x) for x in items[1:4]])
                elif items and items[0]=='l':
                    if len(items)!=3:raise ValueError('expected native two-endpoint line')
                    a,b=[np.asarray(vertices[int(i)-1]) for i in items[1:]]
                    if a.shape!=(3,) or not np.isfinite([a,b]).all():raise ValueError('invalid native line coordinates')
                    total+=1
                    if np.all((a>=lo)&(a<=hi)):starts.append(a);lengths.append(float(np.linalg.norm(b-a)))
        except (ValueError,IndexError) as e:errors.append({'file':str(path),'error':str(e)})
    return dict(available=bool(files) and not errors,retained_lines=total,lines_in_region=len(lengths),
        wall_to_nearest_medial_or_static_point_metres=quantiles(np.asarray(lengths)),
        start_bbox=np.asarray([np.min(starts,axis=0),np.max(starts,axis=0)]).tolist() if starts else None,
        example_start_points=np.asarray(starts[:32]).tolist(),errors=errors,
        measurement='native medialAxisMeshMover debug OBJ lines for projected thickness-ratio truncation',
        limitation='subset where native layer thickness was reduced; retained diagnostic snapshots, processor duplicates possible; not area weighted, full medial field or final layer coverage')


def execute_query(name,args,context):
    if name=='inspect_scenario':
        from .scenario import plan_screen
        scene=context.get('scenario')
        return dict(scenario=scene,configured_screen=plan_screen(context['spec'],context['geometry'],scene) if scene else None,
                    warning='No flow solution yet: separation, vortex trajectory and wake recovery are hypotheses, not measurements.')
    if name=='inspect_plan':
        match=[p for p in catalog(context.get('plan_history',[]),context['budget']) if p['plan_id']==args['plan_id']]
        if len(match)!=1:raise ValueError('unknown measured plan')
        return match[0]
    if name=='query_region':return query_region(args,context)
    if name=='inspect_cluster':
        item=next((d for d in context['evidence'].get('spatial',[]) if d['id']==args['id']),None)
        if item is None:raise ValueError('unknown evidence ID')
        return dict(cluster=item,local=query_region({'min':item['min'],'max':item['max']},context))
    if name=='openfoam_reference':return dict(reference=HELP[args['topic']],layer_parameters=LAYER_PARAMETERS,snap_parameters=SNAP_PARAMETERS,resolution_parameters=RESOLUTION_PARAMETERS,refinement_band_parameters=BAND_PARAMETERS,generation_quality_parameters=GENERATION_QUALITY_PARAMETERS)
    if name=='preview_actions':
        valid={d['id'] for d in context['evidence'].get('spatial',[])}|{'geometry','layers','quality','fidelity','physics'}
        from .scenario import evidence_ids,plan_screen
        scenario=context.get('scenario');valid.update(evidence_ids(scenario))
        valid.update(plan_id(r['spec']) for r in context.get('plan_history',[]))
        actions,notes=normalise_actions(args['actions'],valid)
        candidate=apply_actions(context['spec'],actions,context['geometry'],context['budget'],
                physics_evidence=context['evidence'].get('flow_probe'),physics_reference=context.get('physics'),plan_history=context.get('plan_history'),scenario=scenario,
                spatial_evidence=context['evidence'].get('spatial',[]),resource_calibration=context.get('resource_calibration'))
        from .stages import snap_signature
        if candidate.to_dict()==context['spec'].to_dict():
            raise ValueError('proposal leaves every executable setting unchanged; the protected base may already undo the last failed trial')
        if context.get('mesh_stage')=='snap' and snap_signature(candidate)==snap_signature(context['spec']):
            raise ValueError('proposal does not change snap construction; layer-only settings cannot repair a pre-layer failure')
        next_stage='full' if context.get('mesh_stage')=='full' else ('layers' if snap_signature(candidate) in context.get('snap_anchor_signatures',[]) else 'snap')
        from .candidates import plan_signature
        signature=plan_signature(candidate) if next_stage in ('layers','full') else snap_signature(candidate)
        if (next_stage,signature) in context.get('native_stage_signatures',set()):
            raise ValueError('proposal repeats an already measured native stage; choose a different intervention')
        old=context['spec'].to_dict();new=candidate.to_dict()
        restored=None
        if actions[0]['kind']=='restore_plan':
            restored=apply_actions(context['spec'],actions[:1],context['geometry'],context['budget'],plan_history=context.get('plan_history'),resource_calibration=context.get('resource_calibration'))
        prediction=None;case=context.get('case')
        if any(a['kind']=='wall_height' for a in actions) and case:
            field=max((Path(case)/'flow_probe').glob('*/yPlus'),key=lambda p:float(p.parent.name))
            values,uniform=boundary_scalar(field);areas,_=obj_face_geometry(Path(case)/'body.obj')
            if uniform:values=np.full(len(areas),values[0])
            factor=candidate.layers.first_layer_thickness/context['spec'].layers.first_layer_thickness
            v=values*factor
            prediction=dict(height_multiplier=factor,predicted_area_fraction_30_to_300=float(areas[(v>=30)&(v<=300)].sum()/areas.sum()),
                 assumption='wall shear held fixed; actual native probe must verify because shear can change')
        inactive=[]
        if candidate.layers.first_layer_thickness>0 and candidate.layers.max_face_thickness_ratio!=context['spec'].layers.max_face_thickness_ratio:
            inactive.append('max_face_thickness_ratio: native warped-face check disabled for relativeSizes false; cannot explain a first-height clamp')
        from .mechanisms import intervention_review,region_support
        from .targets import resolve_cluster_actions
        resolved=resolve_cluster_actions(actions,context['evidence'].get('spatial',[]),finest_size(context['spec'],context['geometry']))
        mechanism=intervention_review(restored or context['spec'],candidate,resolved,context['evidence'])
        regions=[a for a in resolved if a['kind'] in ('local_refine','gap_refine','update_region')]
        support=[dict(action=i,box={'min':a['min'],'max':a['max']},before=region_support(restored or context['spec'],context['geometry'],a['min'],a['max']),after=region_support(candidate,context['geometry'],a['min'],a['max'])) for i,a in enumerate(regions)]
        return dict(certification=certify(candidate,context['geometry'],context['budget'],context.get('resource_calibration')),scenario_screen=plan_screen(candidate,context['geometry'],scenario) if scenario else None,interface_normalisation=notes,resolved_measured_actions=resolved,linearised_yplus_prediction=prediction,inactive_parameter_changes=inactive,
            mechanism_review=mechanism,regional_layer_support=support,
            changed_fields={k:new[k] for k in new if new[k]!=old[k]},physical_scales=scales(candidate,context['geometry']),
            restored_anchor_scales=scales(restored,context['geometry']) if restored else None,
            layer_changes_after_restore={k:dict(before=getattr(restored.layers,k),after=getattr(candidate.layers,k)) for k in new['layers'] if getattr(restored.layers,k)!=getattr(candidate.layers,k)} if restored else None,
            limitations='forecast is not calibrated; actual native quality, geometry and layer gates still required')
    raise ValueError('unsupported scientific query')
