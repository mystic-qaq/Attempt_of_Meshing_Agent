"""Immutable flow intent and off-body resolution screening, independent of geometry gates.

These are engineering planning hypotheses, not observed flow or accuracy certificates.
Frame is deliberately explicit: +X inflow, +Z vertical, wing span along Y.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np

FAMILIES = {'vehicle', 'bluff_body', 'finite_wing', 'submerged_body'}
LIMIT = ('Off-body resolution screening only. Wake location is a scenario hypothesis; '
         'flow convergence, mesh sensitivity, forces and engineering accuracy are unverified.')


def validate_context(context):
    allowed = {'family', 'objective', 'boundary_environment', 'flow_direction', 'up_direction',
               'span_direction', 'notes'}
    if not isinstance(context, dict) or set(context)-allowed:
        raise ValueError('unknown scenario fields')
    if context.get('family') not in FAMILIES:
        raise ValueError('unsupported flow family')
    if not isinstance(context.get('objective'), str) or not context['objective'].strip():
        raise ValueError('scenario requires a physical objective')
    if context.get('boundary_environment') != 'unbounded_single_phase':
        raise ValueError('road/ground, free surface and confined flow are not yet supported by this scenario contract')
    if context.get('flow_direction') != [1, 0, 0] or context.get('up_direction') != [0, 0, 1]:
        raise ValueError('geometry must be supplied in +X inflow, +Z up frame')
    if context['family'] == 'finite_wing' and context.get('span_direction') != [0, 1, 0]:
        raise ValueError('finite wing requires span along Y')
    return json.loads(json.dumps(context, allow_nan=False))


def compile_scenario(context, geom, physics):
    context = validate_context(context)
    lo, hi = np.asarray(geom.mesh.bounds, float); length, width, height = hi-lo
    if min(length, width, height) <= 0:
        raise ValueError('scenario requires a finite three-dimensional body')
    family = context['family']; requirements = []
    def add(name, a, b, h, mechanism):
        requirements.append(dict(id='flow_requirement:'+name, name=name, min=list(a), max=list(b),
            max_cell_axis_span_metres=float(h), mechanism=mechanism,
            evidence_status='unvalidated_physical_hypothesis', native_p95_tolerance=1.5,
            source='bounded dimensionless planning prior; requires subsequent flow sensitivity validation'))
    if family == 'finite_wing':
        chord = length
        add('lift_wake', [hi[0],lo[1],lo[2]-.15*chord],
            [hi[0]+2*chord,hi[1],hi[2]+.15*chord], chord/16,
            'trailing-edge vorticity sheet and lift-induced wake; geometry distance alone misses downstream transport')
        for name, y in [('tip_left',lo[1]),('tip_right',hi[1])]:
            add(name,[hi[0],y-.2*chord,lo[2]-.2*chord],
                [hi[0]+2*chord,y+.2*chord,hi[2]+.2*chord],chord/20,
                'potential rolled-up wing-tip vortex; straight corridor is only a starting hypothesis, incidence may deflect it')
    else:
        transverse = min(width,height)
        mechanism = ('rear separation, shear layers and recirculating vehicle wake' if family=='vehicle'
                     else 'separated shear layers and bluff-body wake; steady RANS cannot certify unsteady shedding'
                     if family=='bluff_body' else 'aft-body boundary-layer discharge and velocity-deficit wake; no free-surface effects')
        add('near_wake',[hi[0],lo[1]-.2*width,lo[2]-.2*height],
            [hi[0]+length,hi[1]+.2*width,hi[2]+.2*height],transverse/8,mechanism)
        add('far_wake',[hi[0]+length,lo[1]-.4*width,lo[2]-.4*height],
            [hi[0]+3*length,hi[1]+.4*width,hi[2]+.4*height],transverse/4,
            'downstream transport of velocity deficit and shear; coarser far wake bounds cost')
    identity = dict(context=context, body_bounds_metres=[lo.tolist(),hi.tolist()],
                    reynolds=physics['reynolds'], requirements=requirements)
    signature = hashlib.sha256(json.dumps(identity,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return dict(**identity, contract_sha256=signature,
                scientific_assumptions=['incompressible constant-property single-phase flow',
                    'geometry orientation supplied by user; bounding box does not infer freestream direction',
                    'streamwise body extent is characteristic length; wing span is not chord',
                    'off-body corridors are broad prior envelopes; vortex trajectory and separation require flow evidence',
                    'steady RANS mesh allocation does not validate unsteady shedding or wake recovery'],limitations=LIMIT)


def domain_bounds(spec, geom):
    d=spec.domain;lo,hi=np.asarray(geom.mesh.bounds,float);diag=geom.diagonal
    if d.mode != 'box':
        raise ValueError('scientific off-body actions currently require box domain')
    # Must match case_builder.write_block_mesh_dict: declared +Z vertical.
    return lo-diag*np.array([d.padding_upstream,d.padding_side,d.padding_down]), hi+diag*np.array([d.padding_downstream,d.padding_side,d.padding_up])


def evidence_ids(scenario):
    return {'scenario'}|{r['id'] for r in scenario['requirements']} if scenario else set()


def flow_region(spec, action, geom, scenario):
    from .case_builder import RefinementRegion, DistanceLevel
    if not scenario:
        raise ValueError('flow_refine requires an immutable scenario contract')
    name=action.get('name')
    import re
    if not isinstance(name,str) or not re.fullmatch(r'flow_[A-Za-z0-9_]+',name):
        raise ValueError('flow region name must begin flow_')
    if not set(action.get('evidence',[])) & evidence_ids(scenario):
        raise ValueError('flow refinement must cite scenario or a flow requirement')
    lo=np.asarray(action.get('min'),float);hi=np.asarray(action.get('max'),float)
    if lo.shape!=(3,) or hi.shape!=(3,) or not np.isfinite([lo,hi]).all() or np.any(hi<=lo):
        raise ValueError('flow box requires finite increasing metre bounds')
    dlo,dhi=domain_bounds(spec,geom)
    if np.any(lo<dlo) or np.any(hi>dhi):
        raise ValueError('flow box must remain inside the actual computational domain')
    level=action.get('level')
    if isinstance(level,bool) or not isinstance(level,int) or not 0<=level<=min(9,spec.surface.level_max+2):
        raise ValueError('flow level must be an integer in 0..min(9,surface+2)')
    return RefinementRegion(name=name,shape='box',mode='inside',min=lo.tolist(),max=hi.tolist(),
                            levels=[DistanceLevel(1,level)],why=action['why'])


def prior_actions(spec,geom,scenario):
    from .planning import background_size
    base=background_size(spec,geom)
    return [dict(kind='flow_refine',name='flow_'+r['name'],min=r['min'],max=r['max'],
                 level=max(0,math.ceil(math.log2(base/r['max_cell_axis_span_metres']))),
                 why=r['mechanism'],evidence=[r['id']]) for r in scenario['requirements']]


def plan_screen(spec,geom,scenario):
    """Exact axis-aligned box union partition, not merely a few sampled points."""
    from .planning import background_size
    base=background_size(spec,geom);reports=[];dlo,dhi=domain_bounds(spec,geom)
    for r in scenario['requirements']:
        lo=np.array(r['min']);hi=np.array(r['max']);target=r['max_cell_axis_span_metres']
        boxes=[(np.array(b.min),np.array(b.max)) for b in spec.regions
               if b.shape=='box' and b.mode=='inside' and base/2**b.levels[0].level<=target*(1+1e-12)]
        inside=bool(np.all(lo>=dlo) and np.all(hi<=dhi))
        if base<=target:coverage=1.
        else:
            knots=[sorted(set([lo[i],hi[i]]+[float(np.clip(x[i],lo[i],hi[i])) for box in boxes for x in box])) for i in range(3)]
            # Guard fragmentation before allocating Cartesian partitions.
            if np.prod([len(k)-1 for k in knots])>1_000_000:
                raise ValueError('flow coverage partition too fragmented')
            mids=np.array(np.meshgrid(*[(np.array(k[:-1])+k[1:])/2 for k in knots],indexing='ij')).reshape(3,-1).T
            volumes=np.prod(np.array(np.meshgrid(*[np.diff(k) for k in knots],indexing='ij')),axis=0).ravel()
            covered=np.zeros(len(mids),bool)
            for a,b in boxes:covered|=np.all((mids>=a)&(mids<=b),axis=1)
            coverage=float(volumes[covered].sum()/volumes.sum())
        reports.append(dict(id=r['id'],configured_volume_coverage=coverage,inside_domain=inside,
                            accepted=inside and coverage>=1-1e-10))
    return dict(accepted=all(r['accepted'] for r in reports),requirements=reports,
                limitations='Configured off-body boxes only; native cell measurement is also required. '+LIMIT)


def volume_weighted_span(widths,weights,threshold):
    widths=np.asarray(widths,float);weights=np.asarray(weights,float)
    if widths.ndim!=1 or weights.shape!=widths.shape or not len(widths) or not np.isfinite([widths,weights]).all() or np.any(weights<=0) or np.any(widths<=0):
        raise ValueError('invalid native ROI cell widths or volumes')
    order=np.argsort(widths);cdf=np.cumsum(weights[order])/weights.sum()
    return float(widths[order[min(np.searchsorted(cdf,.95),len(order)-1)]]),float(weights[widths<=threshold].sum()/weights.sum())


def native_screen(case,scenario):
    """Read native volume cells; no solver, no inferred cells from surface geometry."""
    case=Path(case)
    if not all((case/'constant/polyMesh'/name).is_file() for name in ('points','faces','owner','neighbour','boundary')):
        raise ValueError('complete native constant/polyMesh unavailable')
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    marker=case/'scenario_mesh.foam';marker.touch()
    reader=vtk.vtkOpenFOAMReader();reader.SetFileName(str(marker));reader.UpdateInformation()
    reader.DisableAllPatchArrays();reader.SetPatchArrayStatus('internalMesh',1);reader.Update()
    def grids(obj):
        if isinstance(obj,vtk.vtkUnstructuredGrid):yield obj
        elif isinstance(obj,vtk.vtkMultiBlockDataSet):
            for i in range(obj.GetNumberOfBlocks()):yield from grids(obj.GetBlock(i))
    mesh=next(grids(reader.GetOutput()),None)
    if mesh is None or not mesh.GetNumberOfCells():raise ValueError('native internal mesh unavailable')
    centres=vtk.vtkCellCenters();centres.SetInputData(mesh);centres.Update()
    xyz=vtk_to_numpy(centres.GetOutput().GetPoints().GetData())
    sizes=vtk.vtkCellSizeFilter();sizes.SetInputData(mesh)
    sizes.SetComputeArea(False);sizes.SetComputeLength(False);sizes.SetComputeVertexCount(False)
    sizes.SetComputeVolume(True);sizes.Update()
    volume=vtk_to_numpy(sizes.GetOutput().GetCellData().GetArray('Volume'))
    reports=[]
    for r in scenario['requirements']:
        lo=np.array(r['min']);hi=np.array(r['max']);mask=np.all((xyz>=lo)&(xyz<=hi),axis=1);ids=np.flatnonzero(mask)
        widths=[];bins=set()
        for cell_id in ids:
            b=mesh.GetCell(int(cell_id)).GetBounds()
            widths.append(max(b[1]-b[0],b[3]-b[2],b[5]-b[4]))
        if len(ids):
            bins={tuple(x) for x in np.minimum(3,((xyz[ids]-lo)/(hi-lo)*4).astype(int))}
        p95=None;fraction=None
        if widths:
            p95,fraction=volume_weighted_span(widths,volume[ids],r['max_cell_axis_span_metres']*r['native_p95_tolerance'])
        occupied=len(bins)/64
        reports.append(dict(id=r['id'],native_cells=int(len(ids)),spatial_bin_occupancy=occupied,
            p95_cell_axis_span_metres=p95,max_cell_axis_span_metres=float(np.max(widths)) if len(widths) else None,
            resolved_native_roi_cell_volume_fraction=fraction,quantile_weighting='native cell volume; not cell count',
            accepted=bool(p95 is not None and p95<=r['max_cell_axis_span_metres']*r['native_p95_tolerance'] and occupied>=.95)))
    return dict(available=True,accepted=all(r['accepted'] for r in reports),requirements=reports,native_total_cells=int(mesh.GetNumberOfCells()),
        coordinate_precision='VTK reader point precision; near-threshold results require double-precision audit',
        measurement='all native cell centres in ROI; actual cell bounds and volumes, volume-weighted p95 and 4x4x4 occupancy; whole-cell weights, no exact ROI clipping',limitations=LIMIT)
