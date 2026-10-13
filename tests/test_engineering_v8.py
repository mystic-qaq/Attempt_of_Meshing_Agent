import copy
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
from io import StringIO
import numpy as np
from cfdmesh.boundary import observe,ear_triangles
from cfdmesh.case_builder import MeshSpec,render_snappy_hex_mesh_dict
from cfdmesh.plan_validation import validate_plan
from cfdmesh.scientific_tools import plan_tool
from cfdmesh.scientific_advisor import scientific_dialogue
from cfdmesh.io import read_json


class Engineering(unittest.TestCase):
    def test_correction_context_preserves_proposal_and_exact_bounds_without_verbose_history(self):
        from cfdmesh.scientific_advisor import correction_messages
        evidence=dict(budget=12000000,history=['obsolete verbose claim']*100,current_spec=dict(domain={'base_cells':8},quality={'min_face_weight':.05},regions=[{'why':'unrelated box'}]*100),physical_scales={'requested_layer_stack_metres':.00821})
        assistant=dict(role='assistant',content='',reasoning_content='private fixture',tool_calls=[dict(id='p',function={'arguments':'unchanged proposal'})])
        responses=[dict(role='tool',tool_call_id='p',content='received0.02; allowed interval[0.05,0.25]')]
        messages=correction_messages(evidence,assistant,responses);text=json.dumps(messages)
        self.assertIn('unchanged proposal',text);self.assertIn('interval[0.05,0.25]',text)
        self.assertNotIn('private fixture',text);self.assertNotIn('obsolete verbose claim',text);self.assertNotIn('unrelated box',text)
        self.assertIn('base_cells',text);self.assertIn('12000000',text)

    def test_proven_rigid_source_alias_cannot_reset_paid_case_budget(self):
        from cfdmesh.scientific_advisor import geometry_spend,budget_source_alias
        from cfdmesh.io import write_json
        original='1'*64;translated='2'*64
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'work';current=work/'runs/current';prior=work/'runs/prior'
            for run,source,spent in ((current,original,.02),(prior,translated,.03)):
                write_json(run/'manifest.json',dict(source_sha256=source));write_json(run/'advisor/usage.json',dict(estimated_usd=spent))
            write_json(work/'api_budget_scope.json',dict(run_roots=[str(work/'runs')],source_aliases={translated:original}))
            source,total,own=geometry_spend(current)
            self.assertEqual(source,original);self.assertAlmostEqual(total,.05);self.assertAlmostEqual(own,.02)
        with self.assertRaises(ValueError):budget_source_alias(original,{original:translated,translated:original})

    def test_compound_final_and_uncertified_bands_are_repaired_before_native_attempt(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.planning import initial_plan
        from cfdmesh.scientific_tools import execute_query
        from cfdmesh.io import write_json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'box.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=256);spec,physics=initial_plan(geom)
            context=dict(geometry=geom,spec=spec,physics=physics,budget=2000000,evidence={})
            invalid=dict(hypothesis='support depth',expected_change='more extrusion space',actions=[dict(kind='refinement_bands',parameters={'inner_distance':1e-9,'outer_distance':.1},why='normal support',evidence=['geometry'])])
            valid=copy.deepcopy(invalid);valid['actions'][0]['parameters']['inner_distance']=.05
            payloads=[]
            def http(req,timeout):
                payloads.append(json.loads(req.data));i=len(payloads)
                plan=invalid if i<3 else valid
                calls=[dict(id=f'plan{i}_{j}',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(plan))) for j in range(2 if i==1 else 1)]
                return StringIO(json.dumps(dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=dict(role='assistant',content='',tool_calls=calls),finish_reason='tool_calls')])))
            def write(path,data):
                write_json(path,data)
                if Path(path).name.startswith('tool_request_'):
                    try:answer=execute_query(data['name'],data['arguments'],context)
                    except ValueError as exc:answer=dict(error='ValueError: '+str(exc))
                    write_json(Path(path).with_name(Path(path).name.replace('tool_request_','tool_response_')),answer)
            (root/'advisor').mkdir()
            with patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http),patch('cfdmesh.scientific_advisor.write_json',side_effect=write),patch('cfdmesh.runner.run_round') as native:
                result=scientific_dialogue(root,dict(round=0,evidence={}), 'fake-test-credential',root/'advisor/usage.json',24,.5,require_final_preview=True)
            self.assertEqual(result['decision'],valid);self.assertEqual(len(payloads),4)
            self.assertTrue(result['scientific_review_completed'])
            self.assertTrue(result['final_certified_preview']['certification']['ok'])
            self.assertIn('2 refined cells',json.dumps(payloads[2]['messages']))
            self.assertEqual(read_json(root/'advisor/usage.json')['calls'],4);native.assert_not_called()

    def test_rigid_origin_conditioning_preserves_whole_shape_and_source_budget_key(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.io import sha256
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'offset.stl'
            body=trimesh.creation.box(extents=[1.2,.5,.7]);body.apply_translation([42.123,-11.234,17.345]);body.export(source)
            before=sha256(source);geom=prepare(source,root/'input',n=128,centre_geometry=True)
            self.assertEqual(before,sha256(source));self.assertEqual(geom.source_hash,before)
            self.assertFalse(geom.audit['semantic_parts_used']);self.assertEqual(len(geom.mesh.faces),12)
            np.testing.assert_allclose(geom.mesh.bounds.mean(axis=0),0,atol=1e-12)
            original=trimesh.load(source,force='mesh',process=False)
            restored=geom.mesh.triangles+np.array(geom.audit['rigid_origin_conditioning']['source_origin_metres'])
            np.testing.assert_allclose(restored,original.triangles,atol=1e-12,rtol=0)

    def test_native_surface_measurement_preserves_fidelity_gates(self):
        import trimesh
        from cfdmesh.geometry import prepare,fidelity_on_surface
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'box.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=256);wall=geom.mesh.copy()
            self.assertTrue(fidelity_on_surface(geom,wall,.01,n=256)['accepted'])
            wall.apply_scale(1.1)
            result=fidelity_on_surface(geom,wall,.01,n=256)
            self.assertFalse(result['accepted']);self.assertIn('body volume error exceeds 2%',result['reasons'])

    def test_native_point_set_without_cells_retains_spatial_locations(self):
        from cfdmesh.verify import read_vtk_centres
        text='''<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian"><PolyData>
        <Piece NumberOfPoints="2" NumberOfVerts="0" NumberOfLines="0" NumberOfStrips="0" NumberOfPolys="0">
        <Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">1 2 3 4 5 6</DataArray></Points>
        </Piece></PolyData></VTKFile>'''
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'nonManifoldPoints.vtp';file.write_text(text)
            np.testing.assert_allclose(read_vtk_centres(file),[[1,2,3],[4,5,6]])

    def test_generation_limits_only_tighten_independent_gates_unchanged(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.planning import initial_plan,apply_actions
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'box.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=256);spec,_=initial_plan(geom)
            action=dict(kind='generation_quality',parameters={'min_tet_quality':1e-12},why='positive margin',evidence=['quality'])
            new=apply_actions(spec,[action],geom,2000000)
            self.assertEqual(new.quality.check_max_skewness,spec.quality.check_max_skewness)
            for params in ({'min_tet_quality':1e-15},{'max_boundary_skewness':20},{'check_max_skewness':20}):
                bad=copy.deepcopy(action);bad['parameters']=params
                with self.assertRaises(ValueError):apply_actions(new,[bad],geom,2000000)

    def test_nonstar_concave_closed_surface_preserves_notch(self):
        q=np.array([[0,0],[3,0],[3,3],[2,3],[2,1],[1,1],[1,3],[0,3]],float)
        # U-shaped extrusion has area 7, volume 14 and surface area 46.
        vertices=[(*p,z) for z in (0,2) for p in q]
        faces=[list(reversed(range(8))),list(range(8,16))]
        faces.extend([[i,(i+1)%8,(i+1)%8+8,i+8] for i in range(8)])
        text=''.join('v %g %g %g\n'%v for v in vertices)+''.join('f '+' '.join(str(i+1) for i in f)+'\n' for f in faces)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'u.obj';p.write_text(text);before=p.read_bytes()
            mesh,report,parent=observe(p)
            self.assertTrue(mesh.is_watertight);self.assertAlmostEqual(mesh.volume,14)
            self.assertAlmostEqual(mesh.area,46);self.assertEqual(set(parent),set(range(10)))
            self.assertEqual(p.read_bytes(),before)
        with self.assertRaises(ValueError):ear_triangles(np.array([[0,0],[2,2],[0,2],[2,0]],float))

    def test_face_split_and_corner_controls_render_and_validate(self):
        spec=MeshSpec();spec.snap.n_face_split_interval=5;spec.snap.avoid_diagonal=True
        spec.layers.layer_termination_angle=-180;spec.layers.detect_extrusion_island=True
        text=render_snappy_hex_mesh_dict(spec,'body.stl','body',[2,2,2],'body.eMesh')
        for line in ('nFaceSplitInterval 5;','avoidDiagonal true;','layerTerminationAngle -180;','detectExtrusionIsland true;'):
            self.assertIn(line,text)
        spec.snap.n_face_split_interval=0
        with self.assertRaises(ValueError):spec.validate()

    def test_nested_final_schema_rejects_unknown_evidence_or_acceptance_patch(self):
        tool=plan_tool({});base=dict(hypothesis='native topology',expected_change='fewer bad faces',actions=[dict(kind='generation_quality',parameters={'min_tet_quality':1e-12},why='degenerate tetrahedra',evidence=['quality'])])
        validate_plan(base,tool)
        for field,value in (('parameters',{'check_max_skewness':20}),('evidence',['made-up-cluster']),('parameters',{'min_tet_quality':float('nan')})):
            bad=copy.deepcopy(base);bad['actions'][0][field]=value
            with self.assertRaises(ValueError):validate_plan(bad,tool)
        for params in ({'n_face_split_interval':0},{'n_face_split_interval':1.5},{'n_feature_snap_iter':5.5}):
            bad=copy.deepcopy(base);bad['actions'][0]['kind']='snap_settings';bad['actions'][0]['parameters']=params
            with self.assertRaises(ValueError):validate_plan(bad,tool)

    def test_invalid_final_is_repaired_without_meshing_or_private_reasoning(self):
        valid=dict(hypothesis='topology',expected_change='fewer bad faces',actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='diagonal alignment',evidence=['geometry'])])
        invalid=copy.deepcopy(valid);invalid['actions'][0]['parameters']['invented_control']=True
        payloads=[]
        def http(req,timeout):
            payloads.append(json.loads(req.data));choice=invalid if len(payloads)==1 else valid
            message=dict(role='assistant',content='',tool_calls=[dict(id='plan'+str(len(payloads)),type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(choice)))])
            return StringIO(json.dumps(dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=message,finish_reason='tool_calls')])))
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http):
            root=Path(tmp);(root/'advisor').mkdir()
            result=scientific_dialogue(root,dict(round=0,evidence={}), 'fake-test-credential',root/'advisor/usage.json',24,.5)
            self.assertEqual(result['decision'],valid);self.assertEqual(len(payloads),2)
            self.assertEqual(payloads[1]['thinking']['type'],'disabled')
            self.assertIn('invented_control',payloads[1]['messages'][-2]['content'])
            self.assertEqual(read_json(root/'advisor/usage.json')['calls'],2)
