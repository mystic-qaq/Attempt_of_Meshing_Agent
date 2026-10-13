"""Independent layer-count and physical-stack diagnostics, not a CFD certificate."""
from pathlib import Path
import numpy as np
from .verify import boundary_scalar,obj_face_geometry


def area_quantiles(values,areas):
    if not len(values) or areas.sum()<=0:return None
    order=np.argsort(values);cdf=np.cumsum(areas[order]);cdf/=cdf[-1]
    return {f'p{q}':float(values[order][min(np.searchsorted(cdf,q/100),len(values)-1)]) for q in (5,50,95)}


def measure_layer_design(case,spec,original_physics):
    case=Path(case);fields=[p for p in case.glob('*/nSurfaceLayers') if p.parent.name.replace('.','',1).isdigit()]
    if not fields:return dict(available=False,reason='snap phase has no layer field')
    try:
        field=max(fields,key=lambda p:float(p.parent.name));areas,_=obj_face_geometry(case/'body.obj')
        counts,uniform=boundary_scalar(field)
        if uniform:counts=np.full(len(areas),counts[0])
        thickness,uniform=boundary_scalar(field.with_name('thickness'))
        if uniform:thickness=np.full(len(areas),thickness[0])
        if len(counts)!=len(areas) or len(thickness)!=len(areas):raise ValueError('native fields and original boundary face order differ')
        if not np.isfinite([counts,thickness,areas]).all() or np.any(areas<=0) or np.any(thickness<0):raise ValueError('invalid native layer observations')
        original_n=int(original_physics['layers']);h=original_physics['first_layer_height'];r0=original_physics['expansion_ratio']
        target=h*(r0**original_n-1)/(r0-1)
        weight=lambda mask:float(areas[mask].sum()/areas.sum())
        covered=(counts>=1)&(thickness>0);ratio=thickness/target
        result=dict(available=True,original_target_layers=original_n,original_first_height_metres=h,
            original_stack_metres=target,coverage_ge1=weight(counts>=1),coverage_ge5=weight(counts>=5),
            coverage_original_target=weight(counts>=original_n),coverage_current_target=weight(counts>=spec.layers.n_surface_layers),
            requested_layers=spec.layers.n_surface_layers,stack_ratio_area_quantiles=area_quantiles(ratio[covered],areas[covered]),
            area_below_half_original_stack=weight(covered&(ratio<.5)),
            coverage_design_proxy=None,actual_first_cell_height_measured=False,
            limitation='total thickness is native; first height inference assumes one geometric progression; no wall-shear or converged CFD accuracy')
        if spec.layers.n_outer_iter==1:
            first=np.zeros(len(counts));r=spec.layers.expansion_ratio
            first[covered]=thickness[covered]*(r-1)/(r**counts[covered]-1)
            valid=(counts>=original_n)&(first>=.8*h)&(first<=1.2*h)&(ratio>=.5)&(ratio<=1.5)
            result.update(coverage_design_proxy=weight(valid),inferred_first_height_area_quantiles=area_quantiles(first[covered],areas[covered]))
        else:result['first_height_unavailable_reason']='multiple sliced outer passes; single-progression inference withheld'
        return result
    except (ValueError,OSError) as exc:return dict(available=False,reason=str(exc))
