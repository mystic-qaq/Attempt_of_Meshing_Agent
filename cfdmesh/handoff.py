"""Machine-readable downstream contract; partial success never grants readiness."""
from pathlib import Path

def handoff(run):
    records=run.get('rounds',[]);best=run.get('best_provisional_candidate')
    selected=next((r for r in records if r.get('accepted')),None)
    if selected:
        e=selected['evidence'];name=selected['native'].get('case');mesh=Path(name)/'constant/polyMesh' if name else None
        complete=bool(mesh and all((mesh/k).is_file() for k in ('points','faces','owner','neighbour','boundary')))
        layers_ok=not run['config']['require_layers'] or e.get('layers',{}).get('accepted',False)
        screened=bool(e.get('flow_probe',{}).get('near_wall_probe_accepted'))
        screened=screened and (not run.get('scenario') or (e.get('scenario_screen') or {}).get('accepted',False))
        qualified=bool(complete and (e.get('quality') or {}).get('verified') and (e.get('quality') or {}).get('accepted') and e.get('fidelity',{}).get('accepted') and layers_ok and screened and not run.get('source_mutated'))
        experimental=bool(selected['native'].get('native_instrumentation'))
        ready=qualified and not experimental
        return dict(status='screened_mesh_candidate' if ready else 'experimental_screened_mesh' if qualified and experimental else 'mesh_with_unverified_flow',ready_for_rans_screened_handoff=ready,
                    mesh=str(mesh) if mesh else None,source_sha256=run['source_sha256'],code_sha256=run['code_sha256'],
                    flow=run.get('flow'),complete_mesh_artifact=complete,experimental_native_instrumentation=experimental,
                    extended_geometry_accepted=selected['native'].get('extended_geometry_diagnostics',{}).get('accepted'),
                    limitations='experimental native instrumentation is ineligible for automatic handoff; short probe screening only; convergence, mesh sensitivity and engineering accuracy remain unverified')
    return dict(status='running' if run['status']=='running' else 'input_blocked' if run.get('surface_eligibility',{}).get('accepted') is False else 'diagnostic_mesh_only' if best else 'no_verified_mesh',
                ready_for_rans_screened_handoff=False,best_provisional_plan_id=best.get('plan_id') if best else None,
                diagnostic_case=best.get('case') if best else None,source_sha256=run['source_sha256'],code_sha256=run['code_sha256'],
                stop_reason=run.get('stop_reason'),limitations='quality/geometry candidate does not meet the joint layer and flow contract')
