"""Measured geometric constraints and intervention checks; never causal proof."""
import numpy as np

# Installed v2412: these are read by medialAxisMeshMover.C, not by the
# displacementMotionSolverMeshMover. General layer/snap parameters remain active.
MEDIAL_ONLY_PARAMETERS={'n_smooth_normals','max_thickness_to_medial_ratio',
    'min_medial_axis_angle','layer_termination_angle','detect_extrusion_island'}


def stack_height(layers):
    # Explicit sum also handles uniform layers and avoids small-ratio cancellation.
    return float(layers.first_layer_thickness * sum(layers.expansion_ratio**i for i in range(layers.n_surface_layers)))


def region_support(spec,geom,lo,hi,selection=None):
    from .planning import background_size
    lo=np.asarray(lo,float);hi=np.asarray(hi,float)
    mask=np.all((geom.points>=lo)&(geom.points<=hi),axis=1) if selection is None else selection
    points=geom.points[mask];gaps=np.asarray(geom.fluid_gap)[mask]
    h=np.full(len(points),background_size(spec,geom)/2**spec.surface.level_max)
    for region in spec.regions:
        if region.shape=='box' and region.mode=='inside' and not region.gap_level:
            inside=np.all((points>=region.min)&(points<=region.max),axis=1)
            h[inside]=np.minimum(h[inside],background_size(spec,geom)/2**region.levels[0].level)
    finite=np.isfinite(gaps)&(gaps>0);stack=stack_height(spec.layers) if spec.layers.enabled else 0.
    def q(v):return {f'p{i}':float(np.percentile(v,i)) for i in (5,50,95)} if len(v) else None
    return dict(samples=len(points),finite_normal_ray_hits=int(finite.sum()),
        nominal_local_cell_metres=q(h),normal_ray_gap_metres=q(gaps[finite]),
        nominal_cells_across_observed_gap=q(gaps[finite]/h[finite]),
        first_height_to_nominal_cell=q(spec.layers.first_layer_thickness/h) if spec.layers.enabled else None,
        requested_stack_metres=stack,
        two_equal_stacks_exceed_gap_fraction=float(np.mean(2*stack>=gaps[finite])) if finite.any() and stack else None,
        gap_refinement_scope='nominal h excludes gap-triggered levels, whose realised placement requires native measurement',
        interpretation='two equal stacks is an opposing-wall geometric thought experiment, not a native medial or extrusion bound; normal hits can be oblique, an opening may be missed; no finite hits is unknown, not no gaps; no semantic parts')


def intervention_review(before,after,actions,evidence):
    clusters={x['id']:x for x in evidence.get('spatial',[])};warnings=[];targets=[]
    topology=[x['id'] for x in clusters.values() if 'nonmanifold' in x.get('metric','').lower() or x.get('cause')=='boundary_topology']
    for action in actions:
        if action['kind'] in ('local_refine','gap_refine','update_region'):
            lo=np.array(action['min']);hi=np.array(action['max'])
            for ref in action['evidence']:
                if ref not in clusters:continue
                item=clusters[ref]
                if np.any(hi<item['min']) or np.any(lo>item['max']):
                    raise ValueError(f'spatial intervention box does not overlap cited diagnostic {ref}; verify recorded coordinate frame')
                targets.append(ref)
    changed_layers=[k for k,v in after.to_dict()['layers'].items() if v!=before.to_dict()['layers'][k]]
    inactive=[]
    if after.layers.first_layer_thickness>0 and 'max_face_thickness_ratio' in changed_layers:
        inactive.append('max_face_thickness_ratio')
    if after.layers.mesh_shrinker=='displacementMotionSolver':
        inactive.extend(sorted(set(changed_layers)&MEDIAL_ONLY_PARAMETERS))
    if inactive and set(changed_layers)==set(inactive) and before.to_dict()['snap']==after.to_dict()['snap'] and before.to_dict()['regions']==after.to_dict()['regions'] and before.to_dict()['quality']==after.to_dict()['quality'] and before.to_dict()['surface']==after.to_dict()['surface'] and before.to_dict()['domain']==after.to_dict()['domain'] and before.n_cells_between_levels==after.n_cells_between_levels and before.distance_levels==after.distance_levels:
        raise ValueError('intervention changes only inactive parameters in installed v2412 for the selected shrinker/height mode: '+', '.join(inactive)+'; choose an active mechanism')
    if inactive:
        warnings.append('changed parameters inactive for the selected native shrinker/height mode: '+', '.join(inactive)+'; do not attribute a predicted improvement to them')
    if not after.snap.explicit_feature_snap and not after.snap.implicit_feature_snap:
        warnings.append('both feature attraction modes are disabled; check loss of geometric feature alignment before claiming feature iteration or face-splitting benefits')
    if topology and not any(x['kind'] in ('snap_settings','generation_quality','layer_settings','restore_plan','layer_trim','snap_smooth','layer_smooth','transition','refinement_bands') for x in actions):
        warnings.append('measured boundary topology defects remain; refinement alone is a hypothesis, not an extrusion/topology remedy')
    return dict(overlapping_cited_targets=sorted(set(targets)),measured_topology_ids=topology,
        inactive_parameters=inactive,warnings=warnings,
        requested_stack_before_metres=stack_height(before.layers),requested_stack_after_metres=stack_height(after.layers),
        invariant_first_height=before.layers.first_layer_thickness==after.layers.first_layer_thickness,
        limitation='checks spatial consistency and numeric consequences; accepts alternate scientific hypotheses and does not predict native mesh success')
