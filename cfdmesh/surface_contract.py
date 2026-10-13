"""Preserve native diagnostics and optionally add a hash-bound CGAL certificate.

This changes source eligibility only. Native volume, boundary topology and layer
acceptance remain separate gates. Old native-only episodes are never rewritten.
"""
import re
from pathlib import Path
from .io import sha256,read_json,write_json
from .verify import surface_report


def run_independent_audit(surface,executable,directory,environment,deadline):
    from .runner import command
    surface=Path(surface).resolve();executable=Path(executable).resolve();directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    result=directory/'cgal_result.json'
    if result.exists():raise FileExistsError('independent audit receipt already exists')
    before=sha256(surface);binary=sha256(executable)
    step,text=command([executable,surface,result],directory,environment,directory/'cgal.log',deadline)
    certificate=dict(kind='CGAL 5.6.2 EPICK source audit',source_sha256=before,
        executable_sha256=binary,source_mutated=sha256(surface)!=before,
        returncode=step['returncode'],result=read_json(result) if result.exists() else None,
        metrics_sha256=sha256(result) if result.exists() else None,seconds=step['seconds'])
    write_json(directory/'certificate.json',certificate)
    return certificate


def composite_surface_report(text,returncode,surface,certificate=None):
    native=surface_report(text,returncode)
    if certificate is None:return native
    result=certificate.get('result') or {}
    verified=bool(certificate.get('kind')=='CGAL 5.6.2 EPICK source audit'
        and certificate.get('source_sha256')==sha256(surface) and certificate.get('source_mutated') is False
        and certificate.get('returncode')==0 and result.get('accepted') is True
        and result.get('valid_polygon_mesh') is True and result.get('closed') is True
        and result.get('self_intersecting') is False and result.get('outward') is True
        and result.get('components')==1 and result.get('degenerate_triangles')==0
        and result.get('faces',0)>0 and result.get('volume',0)>0)
    complete=returncode==0 and 'FOAM FATAL' not in text and bool(re.search(r'^\s*End\s*$',text,re.M))
    reasons=[]
    if not complete:reasons.append('native surface check incomplete')
    if not native['closed']:reasons.append('native surface closure not affirmative')
    if not verified:reasons.append('independent exact-predicate source certificate failed or mismatched')
    return dict(accepted=not reasons,reasons=reasons,closed=native['closed'],
        self_intersection_free=verified,self_intersection_locations=native['self_intersection_locations'],
        native_report=native,independent_certificate=certificate,
        eligibility_policy='complete native closure plus independent closed/oriented/nondegenerate/single-component/self-intersection-free certificate',
        disagreement=native['self_intersection_free']!=verified)
