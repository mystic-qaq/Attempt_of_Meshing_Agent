import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from cfdmesh.case_builder import MeshSpec,DomainSpec,SurfaceRefinement,RefinementRegion,DistanceLevel
from cfdmesh.scenario import compile_scenario,flow_region,prior_actions,plan_screen,validate_context
from cfdmesh.planning import apply_actions
from cfdmesh.scientific_tools import plan_tool
from cfdmesh.scenario import volume_weighted_span
from unittest.mock import patch


class Scenario(unittest.TestCase):
    def setUp(self):
        self.g=SimpleNamespace(mesh=SimpleNamespace(bounds=np.array([[0.,-.5,0.],[3.,.5,1.]])),diagonal=np.sqrt(11.),longest=3.)
        self.s=MeshSpec(domain=DomainSpec(base_cells=8,padding_downstream=4),surface=SurfaceRefinement(level_min=5,level_max=5))
        self.context=dict(family='vehicle',objective='drag and separated wake',boundary_environment='unbounded_single_phase',flow_direction=[1,0,0],up_direction=[0,0,1])
        self.scene=compile_scenario(self.context,self.g,dict(reynolds=6e6))

    def with_priors(self):
        out=MeshSpec.from_dict(self.s.to_dict())
        out.regions=[flow_region(out,a,self.g,self.scene) for a in prior_actions(out,self.g,self.scene)]
        return out

    def test_geometry_only_cannot_satisfy_wake_contract(self):
        self.assertFalse(plan_screen(self.s,self.g,self.scene)['accepted'])
        out=self.with_priors()
        self.assertTrue(plan_screen(out,self.g,self.scene)['accepted'])
        self.assertLess(out.regions[-1].levels[0].level,self.s.surface.level_max)
        out.regions[-1].min[0]+=1e-3
        self.assertFalse(plan_screen(out,self.g,self.scene)['accepted'])

    def test_union_coverage_detects_tiny_gap_without_sampling(self):
        out=self.with_priors();r=out.regions[0];mid=(r.min[0]+r.max[0])/2
        other=copy.deepcopy(r);other.name='flow_split';other.min[0]=mid
        r.max[0]=mid
        out.regions.append(other)
        self.assertTrue(plan_screen(out,self.g,self.scene)['accepted'])
        other.min[0]+=1e-5
        self.assertFalse(plan_screen(out,self.g,self.scene)['accepted'])

    def test_invalid_or_uncited_offbody_actions_rejected(self):
        action=prior_actions(self.s,self.g,self.scene)[0]
        for change in [dict(level=True),dict(level=-1),dict(min=[float('nan'),0,0]),dict(max=[100,1,1]),dict(evidence=['geometry']),dict(name='body')]:
            with self.assertRaises(ValueError):flow_region(self.s,{**action,**change},self.g,self.scene)
        with self.assertRaises(ValueError):flow_region(self.s,action,self.g,None)

    def test_context_rejects_unsupported_physics_and_is_immutable(self):
        for env in ['moving_ground','free_surface','confined']:
            with self.assertRaises(ValueError):validate_context({**self.context,'boundary_environment':env})
        for frame in [[0,1,0],[float('nan'),0,0]]:
            with self.assertRaises(ValueError):validate_context({**self.context,'flow_direction':frame})
        original=self.scene['contract_sha256'];self.context['objective']='lift'
        self.assertNotEqual(original,compile_scenario(self.context,self.g,dict(reynolds=6e6))['contract_sha256'])

    def test_dimensionless_prior_moves_with_new_body(self):
        shift=np.array([10.,-4.,5.]);self.g.mesh.bounds+=shift
        new=compile_scenario(self.context,self.g,dict(reynolds=6e6))
        np.testing.assert_allclose(np.array(new['requirements'][0]['min'])-np.array(self.scene['requirements'][0]['min']),shift)

    def test_wing_uses_lift_wake_and_two_tip_corridors(self):
        c={**self.context,'family':'finite_wing','span_direction':[0,1,0]}
        scene=compile_scenario(c,self.g,dict(reynolds=6e6))
        self.assertEqual([r['name'] for r in scene['requirements']],['lift_wake','tip_left','tip_right'])
        self.assertTrue(all(r['evidence_status']=='unvalidated_physical_hypothesis' for r in scene['requirements']))

    def test_model_interface_exposes_physics_ids_and_offbody_action(self):
        tool=plan_tool(dict(stage='before first mesh',scenario=self.scene))
        raw=json.dumps(tool)
        self.assertIn('flow_refine',raw);self.assertIn('flow_requirement:near_wake',raw)
        self.assertNotIn('flow_refine',json.dumps(plan_tool(dict(stage='before first mesh'))))

    def test_many_fine_cells_cannot_hide_coarse_wake_volume(self):
        widths=[.01]*100+[1.];volumes=[1e-6]*100+[1.]
        p95,fraction=volume_weighted_span(widths,volumes,.1)
        self.assertEqual(p95,1.);self.assertLess(fraction,.001)
        with self.assertRaises(ValueError):volume_weighted_span([1.],[-1.],.1)

    def test_scenario_removal_is_transactional_even_when_geometry_passes(self):
        out=self.with_priors();before=out.to_dict()
        with patch('cfdmesh.planning.certify',return_value={'ok':True}):
            with self.assertRaisesRegex(ValueError,'off-body'):
                apply_actions(out,[dict(kind='remove_region',name=out.regions[0].name,why='reduce cells',evidence=['scenario'])],self.g,2_000_000,scenario=self.scene)
        self.assertEqual(out.to_dict(),before)

    def test_missing_native_scenario_screen_cannot_grant_handoff(self):
        from cfdmesh.handoff import handoff
        with tempfile.TemporaryDirectory() as tmp:
            mesh=Path(tmp)/'constant/polyMesh';mesh.mkdir(parents=True)
            for name in ('points','faces','owner','neighbour','boundary'):(mesh/name).touch()
            record=dict(accepted=True,native=dict(case=tmp),evidence=dict(quality=dict(verified=True,accepted=True),fidelity=dict(accepted=True),layers=dict(accepted=True),flow_probe=dict(near_wall_probe_accepted=True)))
            run=dict(rounds=[record],config=dict(require_layers=True),source_sha256='s',code_sha256='c',scenario=self.scene)
            self.assertFalse(handoff(run)['ready_for_rans_screened_handoff'])
            record['evidence']['scenario_screen']=dict(accepted=True)
            self.assertTrue(handoff(run)['ready_for_rans_screened_handoff'])

    def test_physical_length_is_independent_of_largest_geometry_extent(self):
        from cfdmesh.planning import initial_plan
        g=SimpleNamespace(mesh=SimpleNamespace(bounds=np.array([[0.,0.,0.],[1.,4.,.2]])),
            diagonal=np.sqrt(17.04),longest=4.,points=np.zeros((8,3)),
            solid_half_thickness=np.full(8,.1),fluid_gap=np.full(8,np.inf))
        a,physical=initial_plan(g,flow_length=1.)
        b,legacy=initial_plan(g)
        self.assertEqual(legacy['reynolds'],4*physical['reynolds'])
        self.assertEqual(a.surface,b.surface)
        self.assertNotEqual(physical['first_layer_height'],legacy['first_layer_height'])

    def test_relative_run_path_keeps_cross_version_cost_scope(self):
        from cfdmesh.scientific_advisor import geometry_spend
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();run=root/'runs/case';run.mkdir(parents=True)
            (run/'manifest.json').write_text(json.dumps({'source_sha256':'s'}))
            (root/'api_budget_scope.json').write_text(json.dumps({'run_roots':[str(root/'runs')]}))
            old=Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(geometry_spend(Path('runs/case')),('s',0.,0.))
            finally:os.chdir(old)

    def test_truncated_thinking_gets_one_budgeted_finalisation(self):
        from cfdmesh.scientific_advisor import scientific_dialogue
        from contextlib import nullcontext
        from io import StringIO
        from cfdmesh.io import read_json
        payloads=[]
        decision=dict(hypothesis='bounded scientific hypothesis',expected_change='specific spatial allocation',disposition='stop',actions=[])
        first=dict(role='assistant',content='',reasoning_content='private truncated fixture')
        last=dict(role='assistant',content='',tool_calls=[dict(id='final',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(decision)))])
        def api(request,**unused):
            payloads.append(json.loads(request.data));i=len(payloads)-1
            return StringIO(json.dumps(dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=[first,last][i],finish_reason=['length','tool_calls'][i])])))
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=api):
            root=Path(tmp);(root/'advisor').mkdir()
            result=scientific_dialogue(root,dict(round=0,evidence={}), 'unit-test-dummy',root/'advisor/usage.json',4,.5,max_output=8192)
            self.assertEqual(result['decision'],decision)
            self.assertEqual(payloads[1]['thinking'],{'type':'disabled'})
            self.assertNotIn('reasoning_effort',payloads[1])
            self.assertEqual(payloads[1]['tool_choice']['function']['name'],'propose_mesh_plan')
            self.assertEqual(payloads[1]['max_tokens'],4096)
            self.assertEqual([t['function']['name'] for t in payloads[1]['tools']],['propose_mesh_plan'])
            self.assertEqual(read_json(root/'advisor/usage.json')['calls'],2)

    def test_asymmetric_domain_uses_declared_z_vertical(self):
        from cfdmesh.case_builder import write_block_mesh_dict
        from cfdmesh.scenario import domain_bounds
        s=copy.deepcopy(self.s)
        s.domain.padding_up=1.;s.domain.padding_down=.5;s.domain.padding_side=2.
        lo,hi=domain_bounds(s,self.g)
        np.testing.assert_allclose(lo[1],-.5-2*self.g.diagonal)
        np.testing.assert_allclose(hi[2],1+self.g.diagonal)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'blockMeshDict'
            meta=write_block_mesh_dict(s,self.g.mesh.bounds[0],self.g.mesh.bounds[1],p)
            # Exported native block must agree with scenario coordinates.
            text=p.read_text();start=text.index('vertices');body=text[start:text.index('blocks',start)]
            import re
            vertices=np.array([[float(x) for x in m] for m in re.findall(r'\(([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\)',body)])
            np.testing.assert_allclose(vertices.min(axis=0),lo,rtol=1e-8)
            np.testing.assert_allclose(vertices.max(axis=0),hi,rtol=1e-8)


if __name__=='__main__':unittest.main()
