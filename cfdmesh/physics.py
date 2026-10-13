from __future__ import annotations
import math
import re
import shutil
import time
from pathlib import Path
import numpy as np
from .io import read_json,write_json,sha256
from .runner import environment,command
from .verify import boundary_scalar,obj_face_areas


def internal_velocity_max(path):
    raw=Path(path).read_bytes();num=r'[-+\d.eE]+'
    start=raw.find(b'internalField')
    if start<0:raise ValueError('internal velocity missing')
    data=raw[start:]
    uniform=re.match(rb'internalField\s+uniform\s*\(([^)]+)\)',data)
    if uniform:values=np.fromstring(uniform.group(1).decode(),sep=' ').reshape(1,3)
    else:
        m=re.match(rb'internalField\s+nonuniform\s+List<vector>\s+(\d+)\s*\(',data)
        if not m:raise ValueError('unsupported internal velocity syntax')
        n=int(m.group(1));payload=data[m.end():]
        if re.search(rb'\bformat\s+binary\s*;',raw[:2000]):
            bits=32 if b'scalar=32' in raw[:2000] else 64;size=n*3*bits//8
            if not payload[size:].lstrip().startswith(b')'):
                skip=2 if payload.startswith(b'\r\n') else 1 if payload.startswith(b'\n') else 0
                if not skip or not payload[size+skip:].lstrip().startswith(b')'):raise ValueError('internal vector list size inconsistent')
                payload=payload[skip:]
            dtype=('<' if b'LSB' in raw[:2000] else '>')+f'f{bits//8}'
            values=np.frombuffer(payload[:size],dtype=dtype).reshape(n,3)
        else:
            vectors=re.findall(rb'\(([^()]+)\)',payload.split(b');',1)[0])
            values=np.asarray([np.fromstring(v.decode(),sep=' ') for v in vectors])
            if values.shape!=(n,3):raise ValueError('internal vector count inconsistent')
    if not len(values) or not np.isfinite(values).all():raise ValueError('nonfinite internal velocity')
    return float(np.linalg.norm(values,axis=1).max())


def field_sanity(time_dir,mesh_source,speed):
    time_dir=Path(time_dir);mesh_source=Path(mesh_source)
    velocity=internal_velocity_max(time_dir/'U');flux={}
    boundary=(mesh_source/'boundary').read_text()
    for patch in ['minX','maxX','minY','maxY','minZ','maxZ','body']:
        values,uniform=boundary_scalar(time_dir/'phi',patch)
        count=re.search(r'\b'+patch+r'\s*\{[^}]*\bnFaces\s+(\d+)',boundary,re.S)
        if not count:raise ValueError('boundary face count unavailable')
        n=int(count.group(1))
        if not uniform and len(values)!=n:raise ValueError('flux face count inconsistent')
        flux[patch]=float(values.sum()*(n if uniform else 1))
    imbalance=abs(sum(flux.values()))/max(abs(flux['minX']),1e-30)
    reasons=[]
    if not np.isfinite(imbalance) or imbalance>.05:reasons.append('net boundary flux exceeds 5% of inlet flux')
    if velocity>10*speed:reasons.append('maximum internal velocity exceeds ten times inlet speed')
    return dict(accepted=not reasons,reasons=reasons,max_internal_velocity=velocity,
                boundary_flux=flux,relative_flux_imbalance=imbalance)


def wall_yplus_report(field_path,surface_path,iterations=30):
    values,uniform=boundary_scalar(field_path)
    areas=obj_face_areas(surface_path)
    if uniform: values=np.full(len(areas),values[0])
    if len(values)!=len(areas) or not len(values) or not np.isfinite(values).all():
        raise ValueError('yPlus values do not match finite body face areas')
    order=np.argsort(values);cdf=np.cumsum(areas[order])/areas.sum()
    quantiles={f'p{q}':float(values[order[min(np.searchsorted(cdf,q/100),len(values)-1)]]) for q in (5,50,95,99)}
    return dict(available=True,area_weighted_quantiles=quantiles,
        area_fraction_30_to_300=float(areas[(values>=30)&(values<=300)].sum()/areas.sum()),
        min=float(values.min()),max=float(values.max()),
        limitation=f'{iterations}-iteration field; stagnation and separation alter wall shear; not a converged RANS certificate')


def numerical_probe(text,speed,extents):
    """Permissive blow-up guards, not convergence or physical validation."""
    num=r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
    continuity=[float(x) for x in re.findall(r'global = ('+num+r')',text)]
    forces=np.asarray([[float(v) for v in line] for line in re.findall(
        r'Total\s*:\s*\(('+num+r')\s+('+num+r')\s+('+num+r')\)',text)])[::2]
    scale=.5*1.225*speed**2*extents[1]*extents[2]
    coefficient=float(np.linalg.norm(forces[-1])/scale) if len(forces) and scale>0 else None
    umax=[float(x) for x in re.findall(r'max\(mag\(U\)\)\s*=\s*('+num+r')',text)]
    reasons=[]
    tail=max(map(abs,continuity[-10:])) if continuity else None
    if tail is None or not np.isfinite(tail) or tail>.01:
        reasons.append('last-ten-step global continuity exceeds permissive 0.01 guard or is missing')
    if coefficient is None or not np.isfinite(coefficient) or coefficient>100:
        reasons.append('force magnitude exceeds 100 dynamic-pressure projected-area units or is missing')
    if umax and (not np.isfinite(umax[-1]) or umax[-1]>10*speed):
        reasons.append('final maximum velocity exceeds ten times inlet speed')
    return dict(accepted=not reasons,reasons=reasons,last_ten_max_abs_global_continuity=tail,
        final_force_magnitude_coefficient=coefficient,force_samples=len(forces),
        final_max_velocity=umax[-1] if umax else None,
        force_last_ten_relative_range=float(np.ptp(forces[-10:,0])/max(abs(forces[-10:,0].mean()),1e-12)) if len(forces) else None,
        purpose='reject obvious numerical blow-up; passing is not a convergence or accuracy certificate')


def header(name,kind='dictionary'):
    return f'FoamFile {{version 2.0; format ascii; class {kind}; object {name};}}\n'


def field(path,name,kind,dimensions,internal,body_type,body_value,external):
    text=header(name,kind)+f'dimensions {dimensions};\ninternalField uniform {internal};\nboundaryField\n{{\n'
    text+=f'body {{ type {body_type}; {body_value} }}\n'
    for patch in ['minX','maxX','minY','maxY','minZ','maxZ']:
        text+=f'{patch} {{ {external(patch)} }}\n'
    text+='}\n';(Path(path)/name).write_text(text)


def solver_smoke(run_dir,of_root,n_procs=8,iterations=30,seconds=600):
    run_dir=Path(run_dir);run=read_json(run_dir/'agent_run.json')
    if not run['accepted']:
        raise ValueError('solver smoke requires an accepted geometry-and-layer mesh')
    source=run_dir/f'round{run["best_round"]}'
    case=run_dir/'solver_smoke'
    return mesh_flow_probe(source,case,run['flow'],run['geometry_audit']['extents'],of_root,n_procs,iterations,seconds)


def mesh_flow_probe(source,case,flow,extents,of_root,n_procs=8,iterations=100,seconds=300,startup_steps=0):
    """Probe a provisional mesh copy; caller must check geometry and mesh quality first."""
    source,case=Path(source),Path(case)
    if case.exists(): raise FileExistsError('solver smoke output immutable')
    (case/'system').mkdir(parents=True);(case/'0').mkdir();(case/'constant').mkdir()
    mesh_source=source/'constant/polyMesh'
    before={p.name:sha256(p) for p in mesh_source.iterdir() if p.is_file()}
    shutil.copytree(mesh_source,case/'constant/polyMesh')
    speed,nu=flow['speed'],flow['nu']
    length=max(extents);k=1.5*(speed*.01)**2
    omega=math.sqrt(k)/(.09**.25 * .07*length)
    field(case/'0','U','volVectorField','[0 1 -1 0 0 0 0]',f'({speed} 0 0)',
          'fixedValue','value uniform (0 0 0);',lambda p:
          f'type fixedValue; value uniform ({speed} 0 0);' if p=='minX' else
          'type zeroGradient;' if p=='maxX' else 'type slip;')
    field(case/'0','p','volScalarField','[0 2 -2 0 0 0 0]','0','zeroGradient','',
          lambda p:'type fixedValue; value uniform 0;' if p=='maxX' else 'type zeroGradient;')
    for name,value,wall in [('k',k,'kqRWallFunction'),('omega',omega,'omegaWallFunction')]:
        field(case/'0',name,'volScalarField','[0 2 -2 0 0 0 0]' if name=='k' else '[0 0 -1 0 0 0 0]',
              str(value),wall,f'value uniform {value};',lambda p:
              f'type fixedValue; value uniform {value};' if p=='minX' else 'type zeroGradient;')
    field(case/'0','nut','volScalarField','[0 2 -1 0 0 0 0]','0','nutkWallFunction','value uniform 0;',
          lambda p:'type calculated; value uniform 0;')
    (case/'constant/transportProperties').write_text(header('transportProperties')+
        f'transportModel Newtonian;\nnu [0 2 -1 0 0 0 0] {nu};\n')
    (case/'constant/turbulenceProperties').write_text(header('turbulenceProperties')+
        'simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs on; }\n')
    (case/'system/fvSchemes').write_text(header('fvSchemes')+'''
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U);
  div(phi,k) bounded Gauss upwind; div(phi,omega) bounded Gauss upwind;
  div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }
''')
    (case/'system/fvSolution').write_text(header('fvSolution')+'''
solvers { p { solver GAMG; tolerance 1e-7; relTol 0.1; smoother GaussSeidel; }
 "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-7; relTol 0.1; } }
SIMPLE { nNonOrthogonalCorrectors 1; consistent yes; }
relaxationFactors { fields { p 0.3; } equations { U 0.7; k 0.7; omega 0.7; } }
''')
    (case/'system/controlDict').write_text(header('controlDict')+f'''
application simpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime {iterations}; deltaT 1;
writeControl timeStep; writeInterval {iterations}; purgeWrite 0;
writeFormat binary; writePrecision 8; runTimeModifiable false;
functions
{{
 yPlus {{ type yPlus; libs (fieldFunctionObjects); writeControl timeStep; writeInterval {iterations}; }}
 fieldBounds {{ type fieldMinMax; libs (fieldFunctionObjects); fields (U p k omega);
                mode magnitude; writeControl timeStep; writeInterval {iterations}; }}
 forces {{ type forces; libs (forces); patches (body); rho rhoInf; rhoInf 1.225;
           CofR (0 0 0); writeControl timeStep; writeInterval 1; }}
}}
''')
    if n_procs>1:
        (case/'system/decomposeParDict').write_text(header('decomposeParDict')+
              f'numberOfSubdomains {n_procs}; method scotch;\n')
    bin_dir=Path(of_root)/'bin';env=environment(of_root);deadline=time.monotonic()+seconds
    original_schemes=(case/'system/fvSchemes').read_text()
    original_solution=(case/'system/fvSolution').read_text()
    original_control=(case/'system/controlDict').read_text()
    if startup_steps:
        if not 1<=startup_steps<=200:raise ValueError('startup_steps must be 1..200')
        (case/'system/fvSchemes').write_text(original_schemes.replace('bounded Gauss linearUpwind grad(U)','bounded Gauss upwind'))
        (case/'system/fvSolution').write_text(original_solution.replace('U 0.7; k 0.7; omega 0.7;','U 0.4; k 0.4; omega 0.4;'))
        (case/'system/controlDict').write_text(original_control.replace(f'endTime {iterations};',f'endTime {startup_steps};'))
    stages=[]
    if n_procs>1:
        stages.append(('decomposePar',[bin_dir/'decomposePar']))
        stages.append(('simpleFoam',[bin_dir/'mpirun','-launcher','fork','-np',str(n_procs),
                                     bin_dir/'simpleFoam','-parallel']))
        stages.append(('reconstructPar',[bin_dir/'reconstructPar','-latestTime']))
    else: stages.append(('simpleFoam',[bin_dir/'simpleFoam']))
    if startup_steps:
        index=next(i for i,(name,argv) in enumerate(stages) if name=='simpleFoam')
        stages.insert(index,('simpleFoam_startup',stages[index][1]))
    report=dict(status='running',steps=[],accepted_for_smoke=False,physical_accuracy='unverified',
                purpose='short numerical operability probe, not convergence or mesh independence',iterations_requested=iterations,
                startup_steps=startup_steps,final_scheme='linearUpwind',startup_scheme='upwind' if startup_steps else None)
    for name,argv in stages:
        if name=='simpleFoam' and startup_steps:
            (case/'system/fvSchemes').write_text(original_schemes)
            (case/'system/fvSolution').write_text(original_solution)
            (case/'system/controlDict').write_text(original_control.replace('startFrom startTime;','startFrom latestTime;').replace(f'endTime {iterations};',f'endTime {iterations+startup_steps};'))
        step,text=command(argv,case,env,case/'logs'/f'{name}.log',deadline)
        step['name']=name;report['steps'].append(step)
        if name=='simpleFoam':
            times=[float(t) for t in re.findall(r'^Time = (\S+)',text,re.M)]
            residuals=[float(x) for x in re.findall(r'Initial residual = ([\d.eE+-]+)',text)]
            continuity=[float(x) for x in re.findall(r'global = ([\d.eE+-]+)',text)]
            yplus=re.findall(r'body y\+ : min = ([\d.eE+-]+), max = ([\d.eE+-]+), average = ([\d.eE+-]+)',text)
            report.update(iterations_completed=max(times) if times else 0,
                    finite_residuals=bool(residuals) and bool(np.isfinite(residuals).all()),
                    max_abs_global_continuity=max(map(abs,continuity)) if continuity else None,
                    final_body_yplus=list(map(float,yplus[-1])) if yplus else None)
            report['accepted_for_smoke']=step['ok'] and bool(times) and max(times)>=iterations+startup_steps and bool(residuals) and bool(np.isfinite(residuals).all())
            report['numerical_sanity']=numerical_probe(text,speed,extents)
            report['accepted_for_smoke'] &= report['numerical_sanity']['accepted']
        if not step['ok']:
            report['error']=name+' failed';report['accepted_for_smoke']=False;break
    final_time=case/str(iterations+startup_steps)
    try:report['field_sanity']=field_sanity(final_time,mesh_source,speed)
    except Exception as e:report['field_sanity']=dict(accepted=False,error=f'{type(e).__name__}: {e}')
    report['accepted_for_smoke'] &= report['field_sanity']['accepted']
    try:
        report['actual_yplus_distribution']=wall_yplus_report(final_time/'yPlus',source/'body.obj',iterations+startup_steps)
    except Exception as e:
        report['actual_yplus_distribution']=dict(available=False,error=f'{type(e).__name__}: {e}')
    yplus=report['actual_yplus_distribution']
    report['near_wall_probe_accepted']=report['accepted_for_smoke'] and yplus.get('available',False) and yplus.get('area_fraction_30_to_300',0)>=.85
    report['near_wall_probe_contract']='at least 85% wall area with actual y+ 30..300 in a numerically sane short probe; not convergence'
    after={p.name:sha256(p) for p in mesh_source.iterdir() if p.is_file()}
    report['source_mesh_mutated']=before!=after
    report['evidence_counts']=dict(cfd_force=len(list((case/'postProcessing/forces').rglob('force*.dat'))),
                                  field=len([p for p in final_time.iterdir() if p.is_file()]) if final_time.exists() else 0)
    report['status']='completed' if report['accepted_for_smoke'] else 'failed'
    write_json(case/'report.json',report)
    return report
