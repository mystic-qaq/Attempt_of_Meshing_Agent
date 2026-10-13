import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from cfdmesh.case_builder import MeshSpec,LayerSpec,RefinementRegion,DistanceLevel,render_snappy_hex_mesh_dict
from cfdmesh.mechanisms import stack_height,region_support,intervention_review


class Mechanisms(unittest.TestCase):
    def test_motion_solver_medial_controls_cannot_be_claimed_as_active(self):
        before=MeshSpec();before.layers.mesh_shrinker='displacementMotionSolver'
        after=MeshSpec.from_dict(before.to_dict());after.layers.layer_termination_angle=-180
        action=dict(kind='layer_settings',parameters={'layer_termination_angle':-180},evidence=['layers'])
        with self.assertRaisesRegex(ValueError,'inactive.*layer_termination_angle'):
            intervention_review(before,after,[action],{})
        after.layers.n_layer_iter+=1
        review=intervention_review(before,after,[action],{})
        self.assertEqual(review['inactive_parameters'],['layer_termination_angle'])
        self.assertTrue(any('inactive' in x for x in review['warnings']))
        after.layers.mesh_shrinker='displacementMedialAxis'
        self.assertNotIn('layer_termination_angle',intervention_review(before,after,[action],{})['inactive_parameters'])

    def test_positive_compute_preview_must_be_seen_before_final_commitment(self):
        import json
        from contextlib import nullcontext
        from io import StringIO
        from unittest.mock import patch
        from cfdmesh.scientific_advisor import scientific_dialogue
        provisional=dict(hypothesis='small-gap hypothesis',expected_change='uncertain layers',actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='test alignment',evidence=['geometry'])])
        corrected=copy.deepcopy(provisional);corrected['hypothesis']='Measured normal gap is not solid half-thickness; unchanged risk fraction is counterevidence'
        preview=dict(certification={'ok':True},physical_scales={'requested_layer_stack_metres':.008},regional_layer_support=[dict(before={'normal_ray_gap_metres':{'p50':.1463},'two_equal_stacks_exceed_gap_fraction':.0763},after={'two_equal_stacks_exceed_gap_fraction':.0763})],mechanism_review={'warnings':['both feature attraction modes disabled']})
        payloads=[]
        def http(request,timeout):
            payloads.append(json.loads(request.data));plan=provisional if len(payloads)==1 else corrected
            return StringIO(json.dumps(dict(usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=dict(role='assistant',content='',tool_calls=[dict(id='p'+str(len(payloads)),type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(plan)))]),finish_reason='tool_calls')])))
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http),patch('cfdmesh.scientific_advisor.final_preview',return_value=preview),patch('cfdmesh.runner.run_round') as native:
            root=Path(tmp);(root/'advisor').mkdir()
            result=scientific_dialogue(root,dict(round=0,evidence={}), 'fake-test-credential',root/'advisor/usage.json',4,.025,max_turns=2,require_final_preview=True)
            self.assertEqual(result['decision'],corrected);self.assertTrue(result['scientific_review_completed'])
            message=json.dumps(payloads[1]['messages'])
            self.assertIn('0.1463',message);self.assertIn('0.0763',message);self.assertIn('do not claim it decreased',message)
            self.assertEqual(payloads[0]['max_tokens'],4096)
            self.assertEqual(payloads[1]['max_tokens'],4096)
            native.assert_not_called()

    def test_last_turn_positive_proposal_cannot_skip_scientific_review(self):
        import json
        from contextlib import nullcontext
        from io import StringIO
        from unittest.mock import patch
        from cfdmesh.scientific_advisor import scientific_dialogue
        decision=dict(hypothesis='unreviewed',expected_change='unknown',actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='alignment',evidence=['geometry'])])
        reply=dict(usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=dict(role='assistant',content='',tool_calls=[dict(id='p',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(decision)))]),finish_reason='tool_calls')])
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',return_value=StringIO(json.dumps(reply))),patch('cfdmesh.scientific_advisor.final_preview',return_value={'certification':{'ok':True}}),patch('cfdmesh.runner.run_round') as native:
            root=Path(tmp);(root/'advisor').mkdir()
            result=scientific_dialogue(root,dict(round=0,evidence={}), 'fake-test-credential',root/'advisor/usage.json',4,.5,max_turns=1,require_final_preview=True)
            self.assertNotIn('decision',result);self.assertIn('not committed',result['error']);native.assert_not_called()

    def test_distribution_and_module_version_agree(self):
        import tomllib
        from cfdmesh import __version__
        self.assertEqual(tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())['project']['version'],__version__)

    def test_default_seed_is_outside_body_inside_domain_without_removed_legacy_module(self):
        import trimesh
        from cfdmesh.case_builder import build_case
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            template=root/'foam/tutorials/incompressible/simpleFoam/motorBike/system';template.mkdir(parents=True)
            for name in ('fvSchemes','fvSolution'):(template/name).write_text('FoamFile {version 2.0; format ascii; class dictionary;}')
            spec=MeshSpec();spec.allow_free_standing_zone_faces=False
            _,info=build_case(spec,source,root/'case',of_project_dir=root/'foam')
            seed=np.array(info['location_in_mesh'])
            self.assertLess(seed[0],-.5)
            self.assertTrue(np.all(seed>info['domain_min']) and np.all(seed<info['domain_max']))

    def test_compacted_parent_cannot_restart_native_or_paid_work(self):
        import trimesh
        from unittest.mock import patch
        from cfdmesh.agent import run_agent
        from cfdmesh.io import sha256,write_json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            parent=root/'old';write_json(parent/'agent_run.json',dict(status='rejected',source_sha256=sha256(source),source_mutated=False))
            write_json(parent/'RETENTION.json',dict(native_artifacts_available_for_resume=False))
            with patch('cfdmesh.agent.run_round') as native,patch('cfdmesh.agent.request_advice') as paid:
                result=run_agent(source,root/'new',root/'foam',resume_from=parent)
            self.assertFalse(result['accepted']);self.assertIn('archived',result['stop_reason'])
            native.assert_not_called();paid.assert_not_called()

    def test_exact_stack_and_unknown_open_space(self):
        layers=LayerSpec(enabled=True,n_surface_layers=6,first_layer_thickness=.00129483932815942,expansion_ratio=1.15)
        self.assertAlmostEqual(stack_height(layers),.011334684797295795,places=12)
        layers.expansion_ratio=1;self.assertAlmostEqual(stack_height(layers),6*layers.first_layer_thickness)
        spec=MeshSpec();spec.layers=layers
        geom=SimpleNamespace(longest=1.,points=np.array([[0.,0.,0.]]),fluid_gap=np.array([np.inf]))
        support=region_support(spec,geom,[-1,-1,-1],[1,1,1])
        self.assertEqual(support['finite_normal_ray_hits'],0)
        self.assertIsNone(support['two_equal_stacks_exceed_gap_fraction'])
        self.assertIsNone(support['normal_ray_gap_metres'])

    def test_opposing_stack_thought_experiment_does_not_change_with_more_cells(self):
        spec=MeshSpec();spec.layers=LayerSpec(enabled=True,n_surface_layers=5,first_layer_thickness=.001,expansion_ratio=1)
        geom=SimpleNamespace(longest=1.,points=np.array([[0.,0.,0.],[.1,0,0]]),fluid_gap=np.array([.004,.02]))
        first=region_support(spec,geom,[-1,-1,-1],[1,1,1])
        spec.regions=[RefinementRegion('repair_0','box','inside',[DistanceLevel(1,7)],min=[-1,-1,-1],max=[1,1,1])]
        finer=region_support(spec,geom,[-1,-1,-1],[1,1,1])
        self.assertEqual(first['two_equal_stacks_exceed_gap_fraction'],.5)
        self.assertEqual(first['two_equal_stacks_exceed_gap_fraction'],finer['two_equal_stacks_exceed_gap_fraction'])
        self.assertGreater(finer['nominal_cells_across_observed_gap']['p50'],first['nominal_cells_across_observed_gap']['p50'])

    def test_box_must_overlap_its_actual_spatial_citation(self):
        spec=MeshSpec();e=dict(spatial=[dict(id='nonManifoldPoints.vtp:0',metric='nonManifoldPoints.vtp',cause='boundary_topology',min=[0,0,0],max=[.1,.1,.1])])
        action=dict(kind='local_refine',min=[1,1,1],max=[2,2,2],evidence=['nonManifoldPoints.vtp:0'])
        with self.assertRaisesRegex(ValueError,'does not overlap'):intervention_review(spec,spec,[action],e)
        action['min']=[0,0,0];action['max']=[.05,.05,.05]
        review=intervention_review(spec,spec,[action],e)
        self.assertTrue(review['warnings']);self.assertEqual(review['overlapping_cited_targets'],action['evidence'])

    def test_inactive_only_proposal_is_rejected_but_active_bundle_can_be_reviewed(self):
        before=MeshSpec();before.layers.first_layer_thickness=.001
        after=MeshSpec.from_dict(before.to_dict());after.layers.max_face_thickness_ratio=.7
        action=dict(kind='layer_settings',parameters={'max_face_thickness_ratio':.7},evidence=['layers'])
        with self.assertRaisesRegex(ValueError,'inactive'):intervention_review(before,after,[action],{})
        after.layers.mesh_shrinker='displacementMotionSolver'
        self.assertEqual(intervention_review(before,after,[action],{})['inactive_parameters'],['max_face_thickness_ratio'])

    def test_gap_action_rendering_budget_and_redundant_boxes(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.planning import initial_plan,apply_actions,forecast
        from cfdmesh.scientific_tools import execute_query,plan_tool
        from cfdmesh.plan_validation import validate_plan
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=256);spec,_=initial_plan(geom)
            action=dict(kind='gap_refine',min=[-.02,-.02,.49],max=[.02,.02,.51],minimum_cells=4,start_level=spec.surface.level_max,max_level=spec.surface.level_max+1,why='probe native gap controls without source labels',evidence=['geometry'])
            validate_plan(dict(hypothesis='bounded gap detection',expected_change='more cells only in native gaps',actions=[action]),plan_tool({}))
            candidate=apply_actions(spec,[action],geom,2000000)
            self.assertEqual(MeshSpec.from_dict(candidate.to_dict()).to_dict(),candidate.to_dict())
            text=render_snappy_hex_mesh_dict(candidate,'body.stl','body',[2,0,0],None)
            self.assertIn(f'gapLevel (4 {spec.surface.level_max} {spec.surface.level_max+1});',text)
            self.assertIn('gapMode outside;',text)
            self.assertGreater(forecast(candidate,geom)['total'],forecast(spec,geom)['total'])
            preview=execute_query('preview_actions',{'actions':[action]},dict(geometry=geom,spec=spec,budget=2000000,evidence={}))
            self.assertTrue(preview['certification']['ok']);self.assertEqual(len(preview['regional_layer_support']),1)
            with self.assertRaisesRegex(ValueError,'already covered'):apply_actions(candidate,[action],geom,2000000)
            local=dict(kind='local_refine',min=[-.03,-.03,.48],max=[.03,.03,.52],level=spec.surface.level_max+1,why='local geometric resolution',evidence=['geometry'])
            refined=apply_actions(spec,[local],geom,2000000)
            nested=copy.deepcopy(local);nested['min']=[-.02,-.02,.49];nested['max']=[.02,.02,.51]
            with self.assertRaisesRegex(ValueError,'already covered'):apply_actions(refined,[nested],geom,2000000)
            excessive=copy.deepcopy(action);excessive['min']=[-100]*3;excessive['max']=[100]*3
            with self.assertRaisesRegex(ValueError,'budget'):apply_actions(spec,[excessive],geom,2000000)

    def test_gap_cannot_change_geometry_side_or_escape_level_cap(self):
        for labels,mode in (([4,5,4],'outside'),([4,0,13],'outside'),([True,0,4],'outside'),([4,0,4],'inside')):
            region=RefinementRegion('gap_0','box','inside',[DistanceLevel(1,0)],min=[0]*3,max=[1]*3,gap_level=labels,gap_mode=mode)
            with self.assertRaises(ValueError):region.validate()


if __name__=='__main__':unittest.main()
