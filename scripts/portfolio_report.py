"""Report every attempt and select only measured, admissible diagnostic meshes."""
import argparse
from pathlib import Path
from cfdmesh.io import read_json, write_json, sha256
from cfdmesh.candidates import eligible
from cfdmesh.scientific_advisor import geometry_spend


def measured_attempt(record, phase, ordinal, root_code):
    e = record['evidence']; q = e.get('quality') or {}; scene = e.get('scenario_screen') or {}
    cells = q.get('metrics', {}).get('cells')
    return dict(attempt=ordinal, phase=phase, case=record['native'].get('case'),
        core_sha256=root_code, decision_origin=record['decision']['source'],
        actions=record['decision'].get('executed_actions', []),
        hypothesis=(record['decision'].get('advisor') or {}).get('hypothesis', record['decision'].get('hypothesis')),
        cells=cells, failed_checks=q.get('n_failed'), quality_accepted=q.get('accepted', False),
        fidelity_accepted=e.get('fidelity', {}).get('accepted', False), scene_accepted=scene.get('accepted', False),
        layer_coverage=e.get('layers', {}).get('coverage'), layers_accepted=e.get('layers', {}).get('accepted', False),
        scene_requirements=scene.get('native', {}).get('requirements', []),
        admissible_diagnostic=eligible(record, 2_000_000) and scene.get('accepted', False),
        joint_accepted=e['accepted'], flow_probe=e.get('flow_probe'), native_error=record['native'].get('error'),
        reasons=e.get('reasons', []), spec=record['spec'],
        native_seconds=record['native'].get('seconds'), parameter_sha256=sha256(Path(record['native']['case']) / 'system/snappyHexMeshDict') if (Path(record['native']['case']) / 'system/snappyHexMeshDict').exists() else None)


def select_attempt(attempts):
    valid = [a for a in attempts if a['admissible_diagnostic'] and a['layer_coverage'] is not None]
    return max(valid, key=lambda a: (a['layer_coverage'], -a['cells'])) if valid else None


def collect(root, out):
    root = Path(root); out = Path(out); protocol = read_json(root / 'portfolio_protocol.json')
    cases = []
    for entry in protocol['cases']:
        run_path = root / 'runs' / entry['id']; run = read_json(run_path / 'agent_run.json')
        if run['status'] == 'running': raise ValueError('cannot finalise an active episode')
        history = read_json(Path(entry['parent']) / 'agent_run.json') if entry['parent'] else None
        attempts = []
        if history:
            for record in history['rounds']:
                attempts.append(measured_attempt(record, 'historical_development', len(attempts)+1, history['code_sha256']))
        for record in run['rounds']:
            attempts.append(measured_attempt(record, 'frozen_portfolio', len(attempts)+1, run['code_sha256']))
        if len(attempts) > 5: raise ValueError('attempt cap violated')
        baseline = attempts[0] if attempts else None; selected = select_attempt(attempts)
        delta = selected['layer_coverage']-baseline['layer_coverage'] if selected and baseline and baseline['layer_coverage'] is not None else None
        _, source_cost, own_cost = geometry_spend(run_path) if (run_path / 'manifest.json').exists() else (None, 0., 0.)
        cases.append(dict(id=entry['id'], family=entry['family'], split=entry['split'],
                          source_sha256=entry['source_sha256'], status=run['status'], stop_reason=run.get('stop_reason'),
                          attempts=attempts, baseline=baseline, selected=selected,
                          layer_gain_percentage_points=100*delta if delta is not None else None,
                          mesh_attempts=len(attempts), new_mesh_attempts=len(run['rounds']),
                          source_api_usd_upper=source_cost, new_api_usd_upper=own_cost,
                          new_wall_seconds=run.get('seconds'), historical_wall_seconds=history.get('seconds', 0) if history else 0,
                          joint_accepted=run['accepted'], handoff=read_json(run_path / 'handoff.json')))
    report = dict(protocol_sha256=sha256(root / 'portfolio_protocol.json'), cases=cases,
                  limitations=protocol['scope'], claim_policy=protocol['claim_policy'])
    write_json(out / 'results.json', report)
    lines = ['# Measured portfolio results', '',
        'The baseline is the identical first mesh of each episode, including the same initial scientific planning. The feedback workflow gets additional attempts, not equal total compute. No geometry-only straw-man control is used.', '',
        'Four development shapes; no statistical or held-out industrial success rate. Vehicle and spheroid include archived V6 attempts and a frozen-core continuation; the two other shapes have new closed-loop episodes. All attempts and code hashes are retained.', '',
        '| Case | One-shot cells / ≥5-layer area | Selected cells / ≥5-layer area | Gain (pp) | Attempts | Selected origin | Joint / screened handoff |',
        '|---|---:|---:|---:|---:|---|---|']
    def display(a):
        return f"{int(a['cells']):,} / {100*a['layer_coverage']:.2f}%" if a and a['cells'] and a['layer_coverage'] is not None else 'no admissible measured selection'
    for c in cases:
        selected = c['selected']; gain = c['layer_gain_percentage_points']
        lines.append(f"| {c['id']} | {display(c['baseline'])} | {display(selected)} | {gain:+.2f}" if gain is not None else f"| {c['id']} | {display(c['baseline'])} | {display(selected)} | —")
        lines[-1] += f" | {c['mesh_attempts']} | {selected['decision_origin'] if selected else 'none'} | {c['joint_accepted']} / {c['handoff']['ready_for_rans_screened_handoff']} |"
    lines += ['', 'Selection was fixed before execution: only native-quality, geometry, scene and budget valid meshes without native pipeline errors qualify; maximise actual ≥5-layer area, then minimise cells. Selecting an earlier candidate is allowed. Rejected attempts cannot win by having high coverage.', '',
              '![Actual layer coverage, including rejected attempts](../assets/feedback_trajectory.png)', '',
              '![Cuts of the actual native volume meshes](../assets/native_mesh_cuts.png)', '',
              'Rejected meshes can contain non-manifold cells which VTK cannot contour. Their cut panels are incomplete diagnostics, explicitly labelled; no rejected mesh is selected because of its appearance.', '',
              '![Native wall layer fields](../assets/native_wall_layers.png)', '']
    for c in cases:
        lines += [f"## {c['id']}", '', f"Stop: {c['stop_reason']}", '',
                  f"New API peak-price upper bound: ${c['new_api_usd_upper']:.6f}; same-source cumulative: ${c['source_api_usd_upper']:.6f}. New wall time: {c['new_wall_seconds']:.1f}s. Counts include unusable answers; no internal model reasoning is exported.", '',
                  '| Attempt | Phase / decision | Cells | ≥5 layers | Q / geometry / scene | Native error |', '|---|---|---:|---:|---|---|']
        for a in c['attempts']:
            coverage = f"{100*a['layer_coverage']:.2f}%" if a['layer_coverage'] is not None else 'unavailable'
            error = (a['native_error'] or 'none').replace('|', '/').replace('\n', ' ')
            lines.append(f"| {a['attempt']} | {a['phase']} / {a['decision_origin']} | {a['cells']} | {coverage} | {a['quality_accepted']} / {a['fidelity_accepted']} / {a['scene_accepted']} | {error} |")
        lines += ['', 'Joint-gate failure reasons for every attempt:', '']
        for a in c['attempts']:
            lines.append(f"- Attempt {a['attempt']}: " + ('; '.join(a['reasons']) or 'all configured checks passed'))
        lines += ['']
    lines += ['## Interpretation limits', '', protocol['scope'], '',
              'Layer coverage is measured from the native final field and weighted by wall area. Pre-solver y+ remains a flat-plate/stack inference. A short SST probe is not force convergence or grid-independence validation. Named wake/tip boxes are physical hypotheses, not measured vortex trajectories.', '',
              'Geometry-only versus science-prior ablations from V6 are documented separately; their changes are deterministic-prior effects and cannot establish LLM or feedback gains.']
    (out / 'RESULTS.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Report complete; all attempts:', sum(c['mesh_attempts'] for c in cases))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('root'); p.add_argument('out')
    args = p.parse_args(); collect(args.root, args.out)
