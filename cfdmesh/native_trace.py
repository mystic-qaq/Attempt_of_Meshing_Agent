"""Typed pre-limit moving-wall point observations, never final face/area claims."""
import re
from pathlib import Path
import numpy as np

def wall_medial_snapshot(case,lo=None,hi=None):
    case=Path(case);ranks=sorted(p for p in case.glob('processor*') if re.fullmatch(r'processor\d+',p.name)) or [case]
    cohorts={}
    for rank in ranks:
        for p in rank.glob('cfdNativeMedialTrace_*.csv'):
            m=re.fullmatch(r'cfdNativeMedialTrace_(\d+)\.csv',p.name)
            if m:cohorts.setdefault(int(m[1]),{})[rank]=p
    complete=[epoch for epoch,files in cohorts.items() if len(files)==len(ranks)]
    if not complete:return dict(available=False,reason='no complete native pre-limit point cohort',ranks=len(ranks),cohorts={str(k):len(v) for k,v in cohorts.items()})
    epoch=max(complete);arrays=[];files=cohorts[epoch]
    expected='epoch,mesh_point,patch_point,x,y,z,medial_distance,medial_x,medial_y,medial_z,wanted_thickness,extrude_status,projected_ratio,ratio_limit'
    try:
        for p in files.values():
            if p.stat().st_size>100_000_000:raise ValueError('trace file exceeds read budget')
            with p.open() as f:
                if f.readline().strip()!=expected:raise ValueError('unrecognised native point schema')
                text=f.read()
            if text.strip():
                from io import StringIO
                a=np.loadtxt(StringIO(text),delimiter=',',ndmin=2)
                if a.shape[1]!=14 or not np.isfinite(a).all() or np.any(a[:,0]!=epoch) or np.any(a[:,6]<0):raise ValueError('invalid native point values/cohort')
                arrays.append(a)
        if not arrays:raise ValueError('complete cohort has no moving-wall points')
    except (ValueError,OSError) as e:return dict(available=False,error=str(e),epoch=epoch)
    all_points=np.vstack(arrays);a=all_points
    if lo is not None:a=a[np.all((a[:,3:6]>=lo)&(a[:,3:6]<=hi),axis=1)]
    def quantiles(x):return {f'p{q}':float(np.percentile(x,q)) for q in (5,50,95)} if len(x) else None
    return dict(available=True,epoch=epoch,ranks=len(ranks),global_master_moving_wall_points=len(all_points),points_in_region=len(a),
        native_fluid_medial_or_static_distance_metres=quantiles(a[:,6]),zero_native_distances=int(np.sum(a[:,6]==0)),
        wanted_displacement_thickness_metres=quantiles(a[:,10]),projected_thickness_ratio=quantiles(a[:,12]),
        pre_limit_ratio_exceedance_fraction=float(np.mean(a[:,12]>a[:,13])) if len(a) else None,
        extrude_status_point_counts={str(int(k)):int(np.sum(a[:,11]==k)) for k in np.unique(a[:,11])},
        bbox=dict(min=all_points[:,3:6].min(axis=0).tolist(),max=all_points[:,3:6].max(axis=0).tolist()),
        files=[str(p.relative_to(case)) for p in files.values()],
        scope='all native master moving-patch points in a sampled pre-limit epoch; matched native meshPoints indexing at that epoch',
        limitation='point count weighted, not wall area or final layer coverage; up to8 sampled epochs; medial seeds include static points; zero may mean unseeded/zero distance, not proof of no fluid space')
