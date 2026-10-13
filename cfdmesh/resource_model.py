"""Measured cell-cost calibration for planning, independent of native acceptance.

The old sum double counts overlapping boxes and solid interiors. Calibrating it
does not make a resource guarantee; the unchanged native cell gate remains final.
"""
from pathlib import Path
from .io import read_json,sha256
from .case_builder import MeshSpec


def fit_full_baseline(record_path,geometry,source_sha256):
    from .planning import forecast
    path=Path(record_path);row=read_json(path);parent=read_json(path.parents[1]/'agent_run.json')
    if parent['status']=='running' or parent['source_sha256']!=source_sha256 or parent.get('source_mutated'):
        raise ValueError('resource calibration requires completed immutable same-source baseline')
    native=row['native'];quality=row['evidence'].get('quality') or {};cells=quality.get('metrics',{}).get('cells')
    if row.get('stage','full')!='full' or not quality.get('verified') or not cells or cells<=0:
        raise ValueError('resource calibration requires a completed full-mesh cell count')
    if not any(s['name']=='snappyHexMesh' and s['ok'] for s in native['steps']):
        raise ValueError('interrupted or capped construction cannot calibrate cell cost')
    if sha256(Path(native['case'])/'constant/triSurface/body.stl')!=sha256(geometry.path):
        raise ValueError('resource calibration input coordinate frame mismatch')
    raw=forecast(MeshSpec.from_dict(row['spec']),geometry)
    background=1.5*raw['background']
    ratio=max(0.,cells-background)/max(1.,raw['total']-background)
    return dict(source_sha256=source_sha256,record_sha256=sha256(path),measured_cells=cells,
        raw_forecast_cells=raw['total'],nonbackground_ratio=ratio,safety_multiplier=2.,
        factor=min(1.,max(.05,2.*ratio)),model='same-source measured nonbackground cost ratio with fixed 2x margin',
        qualification='planning heuristic only; quality-invalid meshes can supply real cell counts; '
            'no guaranteed upper bound or physical accuracy; native final budget gate is unchanged')


def adjusted_forecast(raw,calibration):
    if not calibration:return raw
    import math
    factor=calibration['factor']
    if not math.isfinite(factor) or not .05<=factor<=1. or calibration['safety_multiplier']!=2.:
        raise ValueError('invalid computed resource calibration')
    background=1.5*raw['background']
    return dict(raw,raw_total=raw['total'],total=background+factor*max(0.,raw['total']-background),
        calibration=calibration,resource_guarantee=False)
