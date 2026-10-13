from __future__ import annotations
import os
import re
import signal
import subprocess
import time
import shutil
from pathlib import Path
from .case_builder import build_case
from .io import write_json,read_json,sha256
from .verify import quality_report,surface_report


def environment(of_root):
    root=Path(of_root);env=dict(os.environ)
    env.update(WM_PROJECT_DIR=str(root),WM_PROJECT='OpenFOAM',WM_PROJECT_VERSION='v2412',
               WM_LABEL_SIZE='32',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
               MKL_NUM_THREADS='1',HYDRA_LAUNCHER='fork')
    env['PATH']=str(root/'bin')+os.pathsep+env.get('PATH','')
    env['LD_LIBRARY_PATH']=str(root/'lib')+os.pathsep+env.get('LD_LIBRARY_PATH','')
    return env


def command(argv,cwd,env,log,deadline,cell_limit=None,stall_seconds=300):
    log=Path(log);log.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();reason=None
    with log.open('w') as out:
        out.write('# argv: '+' '.join(map(str,argv))+'\n');out.flush()
        process=subprocess.Popen(list(map(str,argv)),cwd=str(cwd),env=env,
                      stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,
                      start_new_session=True)
        size=0;last_change=started
        while process.poll() is None:
            now=time.monotonic()
            current=log.stat().st_size
            if current!=size: size=current;last_change=now
            if now>=deadline:
                reason='total stage/round deadline reached';break
            if now-last_change>stall_seconds:
                reason=f'no progress output for {stall_seconds}s';break
            if cell_limit and current:
                with log.open('rb') as partial:
                    partial.seek(max(0,current-16000));tail=partial.read().decode(errors='replace')
                counts=[int(x) for x in re.findall(r'\bcells:\s*(\d+)',tail)]
                if counts and max(counts)>cell_limit:
                    reason=f'live cell count exceeds safety limit {cell_limit}';break
            time.sleep(.5)
        if reason:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
            out.write('\n*** KILLED: '+reason+' ***\n')
    text=log.read_text(errors='replace')
    native_fatal=bool(re.search(r'FOAM FATAL|FOAM aborting|MPI_ABORT',text,re.I))
    return dict(argv=list(map(str,argv)),returncode=process.returncode,
                seconds=time.monotonic()-started,log=str(log),reason=reason,
                ok=process.returncode==0 and not reason and not native_fatal),text


def run_round(spec,geometry,case,of_root,n_procs=1,round_seconds=900,budget=2_000_000,
              total_deadline=None,stage='full',snap_anchor=None,input_surface_certificate=None):
    if stage not in ('full','snap','layers'):
        raise ValueError('unknown native mesh stage')
    if (stage=='layers') != (snap_anchor is not None):
        raise ValueError('only a layer stage requires a measured snap anchor')
    case=Path(case)
    if case.exists(): raise FileExistsError('round output is immutable: '+str(case))
    case.mkdir(parents=True)
    env=environment(of_root);bin_dir=Path(of_root)/'bin'
    start=time.monotonic();deadline=min(start+round_seconds,total_deadline or float('inf'))
    result=dict(status='running',steps=[],quality=None,error=None,case=str(case),mesh_stage=stage)
    write_json(case/'round.json',result)
    try:
        layout,info=build_case(spec,geometry,case,of_project_dir=of_root)
        result['layout']=info
        if stage!='full':
            dictionary=case/'system/snappyHexMeshDict';text=dictionary.read_text()
            for name,enabled in (('castellatedMesh',stage=='snap'),('snap',stage=='snap'),('addLayers',stage=='layers')):
                text,count=re.subn(r'\b'+name+r'\s+(?:true|false)\s*;',name+' '+str(enabled).lower()+';',text)
                if count!=1:raise ValueError('ambiguous stage switch '+name)
            dictionary.write_text(text)
        if stage=='layers':
            if not spec.layers.enabled:raise ValueError('layer stage must request layers')
            from .stages import copy_snap
            result['snap_copy']=copy_snap(snap_anchor,case,spec,geometry,budget)
        trace=os.environ.get('CFDMESH_NATIVE_TRACE_LIBRARY');debug_options=['-debug-switch','displacementMedialAxis=1'];extra=[]
        if trace and spec.layers.mesh_shrinker=='displacementMedialAxis':
            library=Path(trace).resolve();manifest=read_json(library.parent/'manifest.json')
            if sha256(library)!=manifest['library_sha256'] or manifest['runtime_type']!='cfdTraceMedialAxis' or manifest.get('trace_debug_default')!=1:raise ValueError('unverified native trace library')
            dictionary=case/'system/snappyHexMeshDict';text=dictionary.read_text()
            replacement,count=re.subn(r'\bmeshShrinker\s+displacementMedialAxis\s*;', 'meshShrinker cfdTraceMedialAxis;',text)
            if count!=1:raise ValueError('native shrinker trace substitution is ambiguous')
            dictionary.write_text(replacement);result['native_instrumentation']=manifest
            extra=['-lib',f'("{library}")'];debug_options=[]
        if n_procs>1:
            (case/'system/decomposeParDict').write_text(
                'FoamFile {version 2.0; format ascii; class dictionary; object decomposeParDict;}\n'
                f'numberOfSubdomains {n_procs};\nmethod scotch;\n')
        # Independent acceptance thresholds, never relaxed by an advisor.
        (case/'system/meshQualityDict').write_text('''
FoamFile {version 2.0; format ascii; class dictionary; object meshQualityDict;}
// Fixed independent acceptance profile; no inherited installation defaults.
maxNonOrtho 70; maxInternalSkewness 4; maxBoundarySkewness 20;
maxConcave 80; minVol 1e-13; minTetQuality 1e-15; minArea -1;
minTwist 0.02; minDeterminant 0.001; minFaceWeight 0.05;
minVolRatio 0.01; minTriangleTwist -1;
nSmoothScale 4; errorReduction 0.75;
''')
        stages=[('surfaceCheck',[bin_dir/'surfaceCheck','-checkSelfIntersection','constant/triSurface/body.stl']),
                ('blockMesh',[bin_dir/'blockMesh']),
                ('surfaceFeatureExtract',[bin_dir/'surfaceFeatureExtract'])]
        if stage=='layers':stages=stages[:1]
        if n_procs>1:
            stages += [('decomposePar',[bin_dir/'decomposePar','-force']),
                       ('snappyHexMesh',[bin_dir/'mpirun','-launcher','fork','-np',str(n_procs),
                                        bin_dir/'snappyHexMesh','-overwrite','-parallel',*debug_options,*extra]),
                       ('reconstructParMesh',[bin_dir/'reconstructParMesh','-constant','-time','none']),
                       ]
            if stage!='snap' and spec.layers.enabled:
                stages += [('reconstructLayers',[bin_dir/'reconstructPar','-withZero','-time','0','-fields',
                                                 '(nSurfaceLayers thickness thicknessFraction)'])]
        else:
            stages += [('snappyHexMesh',[bin_dir/'snappyHexMesh','-overwrite',*debug_options,*extra])]
        stages += [('checkMesh',[bin_dir/'checkMesh','-constant','-time','none','-allTopology',
                                '-meshQuality','-writeSets','vtk','-writeChecks','json']),
                   ('checkMeshExtended',[bin_dir/'checkMesh','-constant','-time','none','-allGeometry','-allTopology','-writeSets','vtk']),
                   ('surfaceMeshExtract',[bin_dir/'surfaceMeshExtract','-constant','-time','none','-patches','(body)','body.obj'])]
        for name,argv in stages:
            result['stage']=name;write_json(case/'round.json',result)
            step,text=command(argv,case,env,case/'logs'/f'{name}.log',deadline,
                              cell_limit=int(budget*1.20) if name=='snappyHexMesh' else None)
            step['name']=name;result['steps'].append(step)
            if name=='snappyHexMesh' and step['ok']:
                times=re.findall(r'^Writing mesh to time\s+(\S+)',text,re.M)
                result['native_declared_final_mesh_time']=times[-1] if times else None
                if not times or times[-1]!='constant':
                    result['error']='native final mesh is not declared at constant; refuse ambiguous artifact selection';break
            if name=='surfaceCheck':
                from .surface_contract import composite_surface_report
                result['surface_eligibility']=composite_surface_report(text,step['returncode'],case/'constant/triSurface/body.stl',input_surface_certificate)
                if not result['surface_eligibility']['accepted']:
                    result['error']='input surface eligibility rejected';break
                if input_surface_certificate:
                    result['native_geometry_check']='native closure complete; independent CGAL source certificate verified; both reports retained'
                    continue
                locations=re.search(r'Surface is self-intersecting at\s+(\d+)\s+locations',text)
                if locations:
                    result['surface_self_intersections']=int(locations.group(1))
                    result['error']=f'native surface check found {locations.group(1)} self-intersection locations';break
                intersections=re.findall(r'(\d+)\s+(?:self[- ]intersecting|intersecting)\s+(?:faces|triangles)',text,re.I)
                if any(int(x)>0 for x in intersections):
                    result['error']='native surface check found self intersections';break
                if 'Surface is not self-intersecting' not in text:
                    result['error']='native surface self-intersection check was not affirmative';break
                result['native_geometry_check']='closed surface and self-intersection check completed'
            if name=='checkMesh':
                result['quality']=quality_report(text,step['returncode'])
                # A fully checked bad mesh is diagnostic evidence; still extract boundary.
                if not result['quality']['verified']:
                    result['error']='checkMesh incomplete or crashed';break
            elif name=='checkMeshExtended':
                result['extended_geometry_diagnostics']=quality_report(text,step['returncode'])
                # Non-FV concavity tests are additional diagnostics, not the basic checkMesh contract.
                if not result['extended_geometry_diagnostics']['verified']:
                    result['error']='extended mesh diagnostic did not complete';break
            elif not step['ok']:
                result['error']=f'{name}: {step["reason"] or "native tool failed"}';break
            if name=='surfaceMeshExtract' and not (case/'body.obj').exists():
                outputs=list(case.glob('body_*.obj'))
                if len(outputs)==1:
                    shutil.copy2(outputs[0],case/'body.obj')
                else:
                    result['error']='boundary extraction has ambiguous/missing time output';break
        if not result['error'] and (case/'body.obj').exists():
            from .boundary import observe
            import trimesh
            try:
                mesh,audit,_=observe(case/'body.obj')
                # Independent native check of the observed representation. Never modify polyMesh.
                (case/'body.observed.stl').write_text(trimesh.exchange.stl.export_stl_ascii(mesh))
                step,text=command([bin_dir/'surfaceCheck','-checkSelfIntersection','body.observed.stl'],
                                  case,env,case/'logs/nativeBoundaryCheck.log',deadline)
                step['name']='nativeBoundaryCheck';result['steps'].append(step)
                audit['native_surface_report']=surface_report(text,step['returncode'])
                audit['native_self_intersection_verified']=step['ok'] and audit['native_surface_report']['accepted']
                result['boundary_observer']=audit
                if not audit['native_self_intersection_verified']:
                    result['error']='observed boundary native self-intersection evidence failed/unavailable'
            except ValueError as e:
                result['boundary_observer']=dict(available=False,error=str(e))
                result['error']='native polygon observation unavailable: '+str(e)
        result['status']='failed' if result['error'] else 'completed'
    except Exception as e:
        result['status']='failed';result['error']=f'{type(e).__name__}: {e}'
    result['seconds']=time.monotonic()-start
    if snap_anchor and result.get('snap_copy'):
        from .stages import verify_snap_unchanged
        result['snap_copy'].update(verify_snap_unchanged(snap_anchor))
    write_json(case/'round.json',result)
    return result
