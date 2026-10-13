import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
import numpy as np
import trimesh
from cfdmesh.io import write_json,read_json
from cfdmesh.geometry import prepare
from cfdmesh.planning import initial_plan,apply_actions,normalise_actions
from cfdmesh.case_builder import render_snappy_hex_mesh_dict
from cfdmesh.scientific_tools import execute_query
from cfdmesh.scientific_advisor import scientific_dialogue,reserve,geometry_spend
from cfdmesh.physics import numerical_probe,internal_velocity_max
from cfdmesh.verify import layer_report


class Scientific(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name)
        source=root/'box.stl';trimesh.creation.box(extents=[1,1,1]).export(source)
        cls.geom=prepare(source,root/'input',n=256);cls.spec,cls.physics=initial_plan(cls.geom)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_mechanism_patch_does_not_change_physics_or_quality(self):
        actions=[dict(kind='layer_settings',parameters={'feature_angle':130,'mesh_shrinker':'displacementMotionSolver','n_outer_iter':2},why='corner mechanism',evidence=['geometry'])]
        s=apply_actions(self.spec,actions,self.geom,2000000)
        self.assertEqual(s.layers.first_layer_thickness,self.spec.layers.first_layer_thickness)
        self.assertEqual(s.quality,self.spec.quality)
        text=render_snappy_hex_mesh_dict(s,'body.stl','body',[2,2,2],'body.eMesh')
        self.assertIn('meshShrinker displacementMotionSolver',text)
        self.assertIn('displacementLaplacianCoeffs',text)
        self.assertIn('nOuterIter 2;',text)

    def test_illegal_parameter_patch_is_rejected(self):
        for params in ({'first_layer_thickness':0},{'n_surface_layers':4},{'n_outer_iter':1.5},
                       {'mesh_shrinker':'shell injection'},{'feature_angle':float('nan')}):
            with self.assertRaises(ValueError):
                apply_actions(self.spec,[dict(kind='layer_settings',parameters=params,why='test',evidence=['layers'])],self.geom,2000000)

    def test_wall_height_requires_sane_flow_and_does_not_compound(self):
        action=[dict(kind='wall_height',scale=1.5,why='actual y+ is below target',evidence=['physics'])]
        with self.assertRaises(ValueError):apply_actions(self.spec,action,self.geom,2000000)
        probe=dict(numerical_sanity={'accepted':True},field_sanity={'accepted':True},actual_yplus_distribution={'available':True})
        s=apply_actions(self.spec,action,self.geom,2000000,probe,self.physics)
        s2=apply_actions(s,action,self.geom,2000000,probe,self.physics)
        self.assertAlmostEqual(s2.layers.first_layer_thickness,self.physics['first_layer_height']*1.5)
        self.assertEqual(s2.quality,self.spec.quality)
        probe['field_sanity']['accepted']=False
        with self.assertRaises(ValueError):apply_actions(s,action,self.geom,2000000,probe,self.physics)

    def test_geometry_query_measures_corners(self):
        result=execute_query('query_region',{},dict(geometry=self.geom,spec=self.spec))
        self.assertEqual(result['dihedral_angle_degrees']['p95'],90)
        self.assertGreater(result['fraction_adjacent_edges_above_layer_feature_angle'],0)
        with self.assertRaises(ValueError):execute_query('query_region',{'min':[0,0,0]},dict(geometry=self.geom,spec=self.spec))

    def test_interface_normalisation_preserves_values_and_rejects_unknown_clusters(self):
        raw=[dict(kind='layer_settings',parameters={'feature_angle':110},why='corner',evidence=['layers.coverage .6','a measured scale annotation'])]
        actions,notes=normalise_actions(raw,{'layers'})
        self.assertEqual(actions[0]['parameters'],raw[0]['parameters'])
        self.assertEqual(actions[0]['evidence'],['layers'])
        self.assertTrue(notes)
        raw[0]['evidence']=['layers','layer_shortfall:999']
        with self.assertRaises(ValueError):normalise_actions(raw,{'layers','layer_shortfall:0'})

    def test_actual_first_height_uses_changed_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'0').mkdir();first=self.physics['first_layer_height'];ratio=1.1
            thick=first*(ratio**8-1)/(ratio-1)
            (root/'0/nSurfaceLayers').write_text('boundaryField {body {type calculated; value uniform 8;}}')
            (root/'0/thickness').write_text(f'boundaryField {{body {{type calculated; value uniform {thick};}}}}')
            obj=root/'body.obj';obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
            result=layer_report(root,obj,self.physics,'',ratio)
            self.assertTrue(result['accepted'])

    def test_finite_explosive_probe_is_rejected(self):
        text='global = .05\nTotal : (1000000 0 0)\nTotal : (0 0 0)'
        self.assertFalse(numerical_probe(text,30,[1,1,1])['accepted'])
        stable='global = .0001\nTotal : (300 0 0)\nTotal : (0 0 0)'
        self.assertTrue(numerical_probe(stable,30,[1,1,1])['accepted'])

    def test_binary_vector_field_finite_maximum(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'U';header=b'FoamFile {format binary; arch "LSB;scalar=64";} internalField nonuniform List<vector> 2 ('
            values=np.array([[3,4,0],[0,0,30]],dtype='<f8')
            p.write_bytes(header+values.tobytes()+b');')
            self.assertEqual(internal_velocity_max(p),30)
            values[0,0]=np.nan;p.write_bytes(header+values.tobytes()+b');')
            with self.assertRaises(ValueError):internal_velocity_max(p)

    def test_flow_failure_reenters_bounded_mesh_loop(self):
        from cfdmesh.agent import run_agent
        from cfdmesh.io import clean
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.stl';trimesh.creation.box().export(source)
            def native(spec,geometry,case,*args):
                Path(case).mkdir();return dict(quality={'accepted':True,'verified':True})
            evidence=dict(accepted=True,reasons=[],quality=dict(accepted=True,n_failed=0,metrics={'cells':1000}),
                fidelity={},layers=dict(accepted=True,coverage=1),spatial=[])
            with patch('cfdmesh.agent.run_round',side_effect=native),patch('cfdmesh.agent.evaluate',side_effect=lambda *a:clean(evidence)),\
                 patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')),\
                 patch('cfdmesh.physics.mesh_flow_probe',return_value=dict(near_wall_probe_accepted=False)) as probe:
                run=run_agent(source,root/'run','/unused',flow_probe=True,max_rounds=2)
            self.assertFalse(run['accepted'])
            self.assertEqual(len(run['rounds']),2)
            self.assertEqual(probe.call_count,2)
            self.assertIn('flow probe rejected',run['rounds'][0]['evidence']['reasons'][0])

    def test_resume_rejects_changed_geometry_before_meshing(self):
        from cfdmesh.agent import run_agent
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.stl';trimesh.creation.box().export(source)
            parent=root/'parent';write_json(parent/'agent_run.json',dict(status='failed',source_sha256='different-source'))
            with patch('cfdmesh.agent.run_round') as native:
                result=run_agent(source,root/'new','/unused',resume_from=parent,max_rounds=4)
            native.assert_not_called();self.assertIn('resume source mismatch',result['stop_reason'])

    def test_resume_does_not_spend_a_round_on_an_unchanged_plan(self):
        from cfdmesh.agent import run_agent
        from cfdmesh.io import sha256
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=Path(self.geom.path);parent=root/'parent'
            write_json(parent/'agent_run.json',dict(status='failed',source_sha256=sha256(source),
                config=dict(budget=2000000,require_layers=True,scale_to_metres=1),flow=self.physics,
                rounds=[dict(round=0,spec=self.spec.to_dict())]))
            with patch('cfdmesh.agent.run_round') as native,patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')):
                result=run_agent(source,root/'new','/unused',resume_from=parent,max_rounds=4)
            native.assert_not_called();self.assertIn('repeated plan blocked',result['stop_reason'])
            self.assertEqual(result['prior_mesh_attempts'],1)

    def test_case_budget_reserves_before_spending(self):
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()):
            ledger=Path(tmp)/'usage.json'
            self.assertTrue(reserve(ledger,.3,24,.5))
            self.assertFalse(reserve(ledger,.3,24,.5))
            self.assertEqual(read_json(ledger)['calls'],1)

    def test_geometry_budget_includes_resumed_and_versioned_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,source,spent in [('previous','same',.3),('resume','same',.02),('other','different',.4)]:
                write_json(root/name/'manifest.json',dict(source_sha256=source))
                write_json(root/name/'advisor/usage.json',dict(estimated_usd=spent))
            source,total,own=geometry_spend(root/'resume')
            self.assertEqual(source,'same');self.assertAlmostEqual(total,.32);self.assertEqual(own,.02)

    def test_thinking_tool_replay_and_private_reasoning(self):
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()):
            root=Path(tmp);(root/'advisor').mkdir();payloads=[]
            def http(req,timeout):
                payloads.append(json.loads(req.data))
                if len(payloads)==1:
                    message=dict(role='assistant',content='',reasoning_content='private reasoning fixture',
                        tool_calls=[dict(id='query1',type='function',function=dict(name='query_region',arguments='{}'))])
                else:
                    message=dict(role='assistant',content=json.dumps(dict(hypothesis='corner',expected_change='coverage above90%',actions=[dict(kind='layer_settings',parameters={'feature_angle':130},why='corner',evidence=['geometry'])])))
                from io import StringIO
                return StringIO(json.dumps(dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=message,finish_reason='tool_calls' if len(payloads)==1 else 'stop')])))
            def write(path,data):
                write_json(path,data)
                if Path(path).name.startswith('tool_request_'):
                    write_json(Path(path).with_name(Path(path).name.replace('tool_request_','tool_response_')),{'dihedral':90})
            with patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http),patch('cfdmesh.scientific_advisor.write_json',side_effect=write):
                answer=scientific_dialogue(root,dict(round=0,evidence={}), 'fake-test-credential',root/'advisor/usage.json',24,.5)
            self.assertEqual(answer['tool_queries'],1)
            self.assertEqual(payloads[1]['messages'][2]['reasoning_content'],'private reasoning fixture')
            self.assertEqual(payloads[1]['messages'][3]['tool_call_id'],'query1')
            self.assertNotIn('private reasoning fixture',json.dumps(read_json(root/'advisor/usage.json')))
            self.assertLess(read_json(root/'advisor/usage.json')['estimated_usd'],.5)

    def test_typed_final_plan_is_consumed(self):
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()):
            root=Path(tmp);(root/'advisor').mkdir()
            decision=dict(hypothesis='corner',expected_change='coverage improvement',actions=[dict(kind='layer_settings',parameters={'feature_angle':110},why='measured90degreecorner',evidence=['geometry'])])
            message=dict(role='assistant',content='',tool_calls=[dict(id='plan',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(decision)))])
            from io import StringIO
            response=dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=message,finish_reason='tool_calls')])
            with patch('cfdmesh.scientific_advisor.urllib.request.urlopen',return_value=StringIO(json.dumps(response))):
                answer=scientific_dialogue(root,dict(round=0,evidence={}), 'fake-test-credential',root/'advisor/usage.json',24,.5)
            self.assertEqual(answer['final_interface'],'typed_function')
            self.assertEqual(answer['decision']['actions'][0]['parameters']['feature_angle'],110)

if __name__=='__main__':unittest.main()
