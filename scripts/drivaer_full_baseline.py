"""One full programmatic mesh from the frozen automatic seed, including source certificates."""
import argparse
import time
from pathlib import Path
from cfdmesh.geometry import prepare
from cfdmesh.case_builder import MeshSpec
from cfdmesh.planning import initial_plan
from cfdmesh.scenario import compile_scenario
from cfdmesh.runner import run_round,environment
from cfdmesh.agent import evaluate
from cfdmesh.drivaer import research_eligible,regional_layers
from cfdmesh.layer_design import measure_layer_design
from cfdmesh.surface_contract import run_independent_audit
from cfdmesh.io import read_json,write_json,code_hash,sha256

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('campaign');p.add_argument('case');p.add_argument('output')
    p.add_argument('--of-root',default=str(Path.home()/'.conda-envs/openfoam2412'));a=p.parse_args()
    campaign=Path(a.campaign).resolve();root=Path(a.output).resolve();protocol=read_json(campaign/'protocol.json')
    if root.exists():raise FileExistsError('baseline output must be fresh')
    if protocol['code_sha256']!=code_hash():raise ValueError('frozen implementation changed')
    entry=next(c for c in protocol['cases'] if c['id']==a.case)
    if entry.get('initial_spec_sha256') and sha256(entry['initial_spec'])!=entry['initial_spec_sha256']:
        raise ValueError('frozen initial specification changed')
    if sha256(entry['source'])!=entry['source_sha256']:raise ValueError('frozen source changed')
    root.mkdir();start=time.monotonic();geom=prepare(entry['source'],root/'input',centre_geometry=True)
    spec=MeshSpec.from_dict(read_json(entry['initial_spec']))
    _,physics=initial_plan(geom,protocol['cell_cap'],flow=dict(speed=30.,nu=1.5e-5,yplus=50.,layers=8),flow_length=geom.mesh.extents[0])
    scenario=compile_scenario(protocol['scenario_context'],geom,physics)
    validator=protocol.get('independent_validator');certificate=None
    if validator:
        if sha256(validator['executable'])!=validator['executable_sha256']:raise ValueError('frozen validator changed')
        certificate=run_independent_audit(geom.path,validator['executable'],root/'input/cgal',environment(a.of_root),time.monotonic()+300)
    native=run_round(spec,geom.path,root/'round0',a.of_root,n_procs=protocol['mpi_processes'],
        round_seconds=protocol['stage_seconds'],budget=protocol['cell_cap'],input_surface_certificate=certificate)
    evidence=evaluate(native,geom,root/'round0',spec,physics,protocol['cell_cap'],require_layers=True,scenario=scenario)
    row=dict(round=0,stage='full',spec=spec.to_dict(),decision={'source':'program_initial_plan'},native=native,evidence=evidence,
        research_eligible=research_eligible(evidence,native,protocol['cell_cap']),regional_layers=regional_layers(root/'round0',geom),
        layer_design=measure_layer_design(root/'round0',spec,physics),accepted=evidence['accepted'])
    result=dict(status='completed' if row['research_eligible'] else 'failed',accepted=row['research_eligible'],rounds=[row],
        source_sha256=entry['source_sha256'],source_mutated=sha256(entry['source'])!=entry['source_sha256'],code_sha256=code_hash(),
        geometry_audit=geom.audit,flow=physics,scenario=scenario,config=dict(budget=protocol['cell_cap'],model_used=False),seconds=time.monotonic()-start)
    write_json(root/'round0/record.json',row);write_json(root/'agent_run.json',result)
    print(result['status'],'actual >=5 area',evidence['layers'].get('coverage'),'research eligible',row['research_eligible'],flush=True)
