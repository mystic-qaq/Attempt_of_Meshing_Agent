"""Source- and control-matched observations; never turn failed meshes into anchors."""
from pathlib import Path
from .io import read_json,sha256
from .case_builder import MeshSpec
from .stages import snap_signature


def load_stage_comparison(snap_record,full_record,source_sha256,centred_sha256):
    paths=[Path(snap_record),Path(full_record)];rows=[read_json(p) for p in paths]
    for path,row,stage in zip(paths,rows,('snap','full')):
        parent=read_json(path.parents[1]/'agent_run.json')
        if parent['status']=='running' or parent['source_sha256']!=source_sha256 or parent.get('source_mutated'):
            raise ValueError('stage comparison requires completed immutable same-source evidence')
        if row['stage']!=stage or not row['evidence'].get('quality',{}).get('verified'):
            raise ValueError('stage comparison requires completed snap and full quality observations')
        if sha256(Path(row['native']['case'])/'constant/triSurface/body.stl')!=centred_sha256:
            raise ValueError('stage comparison coordinate frame mismatch')
    signatures=[snap_signature(MeshSpec.from_dict(r['spec'])) for r in rows]
    if signatures[0]!=signatures[1]:raise ValueError('stage comparison has different snap controls')
    def view(path,row):
        return dict(record_sha256=sha256(path),stage=row['stage'],quality=row['evidence']['quality'],
            native_error=row['native'].get('error'),research_eligible=row['research_eligible'],
            coverage_ge5=row['evidence']['layers'].get('coverage'))
    before,after=[view(p,r) for p,r in zip(paths,rows)]
    import hashlib
    return dict(source_sha256=source_sha256,snap_signature_sha256=hashlib.sha256(signatures[0].encode()).hexdigest(),before_layers=before,
        after_layers=after,snap_controls_matched=True,
        baseline_snap_settings=rows[0]['spec']['snap'],baseline_surface=rows[0]['spec']['surface'],
        interpretation='Separate native executions with identical snap controls and input. '
            'A newly observed full-mesh defect implicates layer construction/interaction; '
            'it does not prove a unique cause. The snap mesh can still be invalid for other reasons. '
            'These diagnostics do not authorize copying either mesh as an anchor.')
