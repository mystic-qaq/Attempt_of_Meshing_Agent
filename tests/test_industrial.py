import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np,trimesh
from cfdmesh.geometry import prepare
from cfdmesh.io import sha256,write_json
from cfdmesh.agent import run_agent
from cfdmesh.scientific_advisor import geometry_spend
from cfdmesh.planning import initial_plan,apply_actions,normalise_actions

class Industrial(unittest.TestCase):
    def test_normal_support_bands_are_jointly_validated_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            g=prepare(source,root/'input',n=128);s,_=initial_plan(g)
            from cfdmesh.planning import finest_size
            h=finest_size(s,g);distances=[2.5*h,6.5*h]
            bands={'kind':'refinement_bands','parameters':dict(zip(['inner_distance','outer_distance'],distances)),'why':'normal support for shrink','evidence':['geometry']}
            resolution={'kind':'resolution_settings','parameters':{'surface_level':s.surface.level_max},'why':'same tangential resolution','evidence':['geometry']}
            a=apply_actions(s,[bands,resolution],g,2000000);b=apply_actions(s,[resolution,bands],g,2000000)
            self.assertEqual(a.to_dict(),b.to_dict());self.assertEqual(a.layers,s.layers);self.assertEqual(a.quality,s.quality)
            self.assertEqual([x.distance for x in a.distance_levels],distances)
            self.assertEqual([x.distance for x in apply_actions(a,[resolution],g,2000000).distance_levels],distances)
            bands['parameters']['outer_distance']=.01
            with self.assertRaisesRegex(ValueError,'physical bands'):apply_actions(s,[bands],g,2000000)
            bands['parameters']={'inner_distance':g.diagonal/2,'outer_distance':g.diagonal}
            with self.assertRaisesRegex(ValueError,'budget'):apply_actions(s,[bands],g,2000000)

    def test_legacy_smoothing_cannot_reduce_explicitly_selected_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            g=prepare(source,root/'input',n=128);s,_=initial_plan(g)
            actions=[{'kind':'layer_settings','parameters':{'n_relax_iter':15,'n_layer_iter':100,'n_smooth_normals':15,'n_smooth_thickness':30},'why':'measured layer failure','evidence':['layers']},
                     {'kind':'layer_smooth','why':'continue smoothing','evidence':['layers']}]
            out=apply_actions(s,actions,g,2000000)
            self.assertEqual((out.layers.n_relax_iter,out.layers.n_layer_iter,out.layers.n_smooth_normals,out.layers.n_smooth_thickness),(15,100,15,30))

    def test_closed_float32_roundtrip_cannot_silently_change_translated_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=trimesh.creation.box(extents=[.1,.2,.3]);m.apply_translation([1e6,0,0])
            source=root/'source.stl';source.write_text(trimesh.exchange.stl.export_stl_ascii(m))
            g=prepare(source,root/'input',n=128)
            self.assertEqual(g.audit['canonical_precision'],'ASCII float64')
            self.assertGreater(g.audit['binary_roundtrip_max_coordinate_error_metres'],.001)
            np.testing.assert_allclose(g.mesh.extents,m.extents,rtol=0,atol=1e-10)

    def test_preview_exposes_inactive_absolute_height_warp_parameter(self):
        from cfdmesh.scientific_tools import execute_query
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            g=prepare(source,root/'input',n=128);s,p=initial_plan(g)
            action={'kind':'layer_settings','parameters':{'max_face_thickness_ratio':.7},'why':'check actual native activity','evidence':['geometry']}
            context={'spec':s,'geometry':g,'budget':2000000,'evidence':{},'physics':p}
            with self.assertRaisesRegex(ValueError,'inactive'):execute_query('preview_actions',{'actions':[action]},context)
            action['parameters']['mesh_shrinker']='displacementMotionSolver'
            result=execute_query('preview_actions',{'actions':[action]},context)
            self.assertTrue(result['inactive_parameter_changes'])
            self.assertFalse(result['physical_scales']['native_layer_semantics']['max_face_thickness_ratio_active'])

    def test_nonfinal_snappy_output_stops_before_reconstruction_or_check(self):
        from cfdmesh.runner import run_round
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seen=[]
            def build(*args,**kwargs):
                (Path(args[2])/'system').mkdir();return {},{}
            def native(argv,*args,**kwargs):
                name=Path(argv[0]).name;seen.append(name)
                text='Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n' if name=='surfaceCheck' else 'Writing mesh to time 137\nEnd\n'
                return {'ok':True,'returncode':0},text
            with patch('cfdmesh.runner.build_case',side_effect=build),patch('cfdmesh.runner.command',side_effect=native):
                result=run_round(None,'unused',root/'case','/unused')
            self.assertIn('ambiguous artifact selection',result['error']);self.assertNotIn('checkMesh',seen)
            self.assertEqual(result['native_declared_final_mesh_time'],'137')

    def test_incomplete_native_quality_cannot_trigger_paid_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.stl';trimesh.creation.box().export(source)
            evidence={'accepted':False,'reasons':['interrupted native check'],'quality':{'verified':False},'fidelity':{},'layers':{},'spatial':[]}
            with patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')),patch('cfdmesh.agent.run_round',return_value={'quality':{'verified':False},'error':'interrupted'}),patch('cfdmesh.agent.evaluate',return_value=evidence),patch('cfdmesh.agent.request_advice') as paid:
                r=run_agent(source,root/'run','/unused',advisor='deepseek-flash')
            paid.assert_not_called();self.assertEqual(len(r['rounds']),1)
            self.assertIn('native pipeline failed',r['stop_reason'])

    def test_native_truncation_positions_are_regional_and_not_full_wall_field(self):
        from cfdmesh.scientific_tools import truncation_lines
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'native.obj';p.write_text('v 0 0 0\nv 0 0 .01\nl 1 2\nv 2 0 0\nv 2 0 .2\nl 3 4\n')
            r=truncation_lines([p],np.array([-1,-1,-1]),np.array([1,1,1]))
            self.assertTrue(r['available']);self.assertEqual(r['retained_lines'],2);self.assertEqual(r['lines_in_region'],1)
            self.assertAlmostEqual(r['wall_to_nearest_medial_or_static_point_metres']['p50'],.01)
            self.assertIn('subset',r['limitation'])

    def test_flattened_model_parameters_are_packaged_without_numeric_changes(self):
        raw=[{'kind':'layer_settings','feature_angle':110,'n_outer_iter':2,'why':'measured corners','evidence':['geometry']}]
        actions,notes=normalise_actions(raw,{'geometry'})
        self.assertEqual(actions[0]['parameters'],{'feature_angle':110,'n_outer_iter':2})
        self.assertTrue(notes);self.assertIn('feature_angle',raw[0])
        raw[0]['parameters']={'feature_angle':100}
        with self.assertRaisesRegex(ValueError,'conflicting'):normalise_actions(raw,{'geometry'})

    def test_native_rejection_precedes_paid_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.stl';trimesh.creation.box().export(source)
            with patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nFound 12 self-intersections\nEnd\n')),patch('cfdmesh.agent.request_advice') as paid,patch('cfdmesh.agent.run_round') as native:
                result=run_agent(source,root/'run','/unused',advisor='deepseek-flash',model_plan=True)
            paid.assert_not_called();native.assert_not_called()
            self.assertEqual(result['status'],'blocked');self.assertEqual(result['rounds'],[])
            self.assertIn('before paid planning',result['stop_reason'])

    def test_single_shell_winding_normalisation_preserves_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=trimesh.creation.box();m.faces[0]=m.faces[0][::-1]
            source=root/'input.stl';m.export(source);before=sha256(source)
            g=prepare(source,root/'normalised',n=128)
            self.assertTrue(g.mesh.is_watertight and g.mesh.is_winding_consistent)
            self.assertTrue(g.audit['single_shell_winding_normalised'])
            self.assertEqual(len(m.faces),len(g.mesh.faces));self.assertAlmostEqual(g.mesh.volume,1)
            self.assertEqual(before,sha256(source))
            np.testing.assert_array_equal(np.sort(m.vertices,axis=0),np.sort(g.mesh.vertices,axis=0))

    def test_versioned_runs_share_geometry_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'v3/runs/old';new=root/'v4/runs/new';other=root/'v3/runs/other'
            for p,key,cost in [(old,'body',.3),(new,'body',.12),(other,'different',.5)]:
                write_json(p/'manifest.json',{'source_sha256':key});write_json(p/'advisor/usage.json',{'estimated_usd':cost})
            write_json(root/'v4/api_budget_scope.json',{'run_roots':[str(old.parent),str(new.parent)]})
            source,total,own=geometry_spend(new)
            self.assertEqual(source,'body');self.assertAlmostEqual(total,.42);self.assertAlmostEqual(own,.12)
            write_json(root/'v4/api_budget_scope.json',{'run_roots':[str(root/'missing')]})
            with self.assertRaises(ValueError):geometry_spend(new)

    def test_resolution_patch_keeps_contract_and_rejects_fractional_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'body.stl';trimesh.creation.box().export(source)
            g=prepare(source,root/'input',n=128);s,_=initial_plan(g)
            action={'kind':'resolution_settings','parameters':{'surface_level':s.surface.level_max,'base_cells':8},'why':'allocate global budget before local repair','evidence':['geometry']}
            changed=apply_actions(s,[action],g,2000000)
            self.assertEqual(changed.quality,s.quality);self.assertEqual(changed.layers,s.layers)
            action['parameters']['surface_level']=2.5
            with self.assertRaises(ValueError):apply_actions(s,[action],g,2000000)

if __name__=='__main__':unittest.main()
