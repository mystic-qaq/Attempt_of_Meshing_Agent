import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from cfdmesh.case_builder import MeshSpec
from cfdmesh.io import write_json
from cfdmesh.stages import CORE, register_snap, copy_snap, mesh_hashes, verify_snap_unchanged, snap_signature
from cfdmesh.drivaer import research_eligible, update_archive
from cfdmesh.scientific_advisor import scientific_dialogue,compact_model_evidence


class DrivAerStageTest(unittest.TestCase):
    def test_cluster_targets_preserve_measured_axis_order_and_exact_box(self):
        from cfdmesh.targets import resolve_cluster_actions
        targets=[dict(id='native:1',min=[-.67,-1.,.21],max=[-.52,-.85,.35])]
        action=dict(kind='cluster_refine',ids=['native:1'],level=6,padding_cells=1,
                    why='measured topology',evidence=['native:1'])
        resolved=resolve_cluster_actions([action],targets,.01)[0]
        import numpy as np
        np.testing.assert_allclose(resolved['min'],[-.68,-1.01,.20])
        np.testing.assert_allclose(resolved['max'],[-.51,-.84,.36])
        bad=copy.deepcopy(action);bad['ids']=['made-up']
        with self.assertRaises(ValueError):resolve_cluster_actions([bad],targets,.01)

    def test_typed_cluster_plan_schema_accepts_valid_ids_and_rejects_duplicates(self):
        from cfdmesh.plan_validation import validate_plan
        from cfdmesh.scientific_tools import plan_tool
        tool=plan_tool({'spatial':[{'id':'measured:1'}]})
        plan=dict(hypothesis='measured boundary',expected_change='native verification',actions=[dict(kind='cluster_refine',ids=['measured:1'],level=8,padding_cells=0,why='small observed gap',evidence=['measured:1'])])
        validate_plan(plan,tool)
        plan['actions'][0]['ids']*=2
        with self.assertRaisesRegex(ValueError,'duplicate'):validate_plan(plan,tool)

    def test_fine_measured_target_is_resource_checked_and_cannot_be_spoofed(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.planning import initial_plan,apply_actions,certify
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'box.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=64);spec,_=initial_plan(geom)
            target={'id':'measured:1','min':[-.01,-.01,.49],'max':[.01,.01,.51]}
            act=dict(kind='cluster_refine',ids=[target['id']],level=spec.surface.level_max+3,padding_cells=0,why='measured narrow feature',evidence=[target['id']])
            candidate=apply_actions(spec,[act],geom,2_000_000,spatial_evidence=[target])
            self.assertTrue(certify(candidate,geom,2_000_000)['ok'])
            raw=dict(kind='local_refine',min=target['min'],max=target['max'],level=act['level'],why='unmeasured box',evidence=['geometry'])
            with self.assertRaisesRegex(ValueError,'surface\+2'):apply_actions(spec,[raw],geom,2_000_000)
            raw['compiled_measured_target']=target['id']
            with self.assertRaisesRegex(ValueError,'compiler'):apply_actions(spec,[raw],geom,2_000_000)
            huge=dict(target,min=[-.6]*3,max=[.6]*3)
            with self.assertRaisesRegex(ValueError,'projected cells'):apply_actions(spec,[act],geom,2_000_000,spatial_evidence=[huge])

    def test_preview_rejects_noop_layer_only_snap_repair_and_measured_stage(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.planning import initial_plan,apply_actions
        from cfdmesh.scientific_tools import execute_query
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'box.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=64);spec,physics=initial_plan(geom)
            context=dict(geometry=geom,spec=spec,physics=physics,budget=2_000_000,evidence={},mesh_stage='snap')
            noop=dict(kind='snap_settings',parameters={'n_smooth_patch':spec.snap.n_smooth_patch},why='repeat',evidence=['geometry'])
            with self.assertRaisesRegex(ValueError,'unchanged'):execute_query('preview_actions',{'actions':[noop]},context)
            layer=dict(kind='layer_settings',parameters={'expansion_ratio':1.15},why='wrong phase',evidence=['geometry'])
            with self.assertRaisesRegex(ValueError,'pre-layer'):execute_query('preview_actions',{'actions':[layer]},context)
            repair=dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='native diagonal',evidence=['geometry'])
            candidate=apply_actions(spec,[repair],geom,2_000_000)
            context['native_stage_signatures']={('snap',snap_signature(candidate))}
            with self.assertRaisesRegex(ValueError,'already measured'):execute_query('preview_actions',{'actions':[repair]},context)
            context['mesh_stage']='full';context['native_stage_signatures']=set()
            # Full-pipeline diagnostics must allow layer interventions even when
            # the same parameters cannot repair a pre-layer construction step.
            self.assertTrue(execute_query('preview_actions',{'actions':[layer]},context)['certification']['ok'])

    def test_snap_region_query_preserves_geometry_when_no_layer_field_exists(self):
        import trimesh
        from cfdmesh.geometry import prepare
        from cfdmesh.planning import initial_plan
        from cfdmesh.scientific_tools import query_region
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'box.stl';trimesh.creation.box().export(source)
            geom=prepare(source,root/'input',n=64);spec,_=initial_plan(geom)
            case=root/'snap';case.mkdir()
            (case/'body.obj').write_text('v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n')
            result=query_region({},dict(geometry=geom,spec=spec,case=case,evidence={}))
            self.assertEqual(result['geometry_samples'],64)
            self.assertIn('layer_support',result)
            self.assertFalse(result['actual_layers']['available'])
            self.assertEqual(result['native_boundary_polygons']['faces_in_region'],1)
            self.assertEqual(result['native_boundary_polygons']['bbox_span_by_axis_metres']['x']['p50'],1.)

    def test_copied_anchor_is_independent_and_rejects_mutated_geometry_or_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'snap';mesh=source/'constant/polyMesh';mesh.mkdir(parents=True)
            (source/'constant/triSurface').mkdir()
            geom=root/'body.stl';geom.write_text('preserved source')
            for name in CORE:(mesh/name).write_text(name)
            spec=MeshSpec();e=dict(accepted=True,quality=dict(accepted=True,metrics={'cells':100}),fidelity={'accepted':True},scenario_screen={'accepted':True})
            anchor=register_snap(source,spec,geom,e,1000)
            dest=root/'trial';(dest/'constant/triSurface').mkdir(parents=True)
            spec.layers.n_surface_layers+=1
            copy_snap(anchor,dest,spec,geom,1000)
            self.assertEqual(mesh_hashes(dest),anchor['poly_mesh_sha256'])
            (dest/'constant/polyMesh/points').write_text('trial changed')
            self.assertFalse(verify_snap_unchanged(anchor)['source_mutated'])
            spec.snap.n_smooth_patch+=1
            with self.assertRaisesRegex(ValueError,'controls changed'):copy_snap(anchor,root/'other',spec,geom,1000)
            spec.snap.n_smooth_patch-=1;geom.write_text('different input')
            with self.assertRaisesRegex(ValueError,'geometry'):copy_snap(anchor,root/'other',spec,geom,1000)

    def test_scene_failure_cannot_be_an_anchor_or_research_candidate(self):
        e=dict(accepted=False,quality=dict(accepted=True,verified=True,metrics={'cells':100}),fidelity={'accepted':True},scenario_screen={'accepted':False})
        self.assertFalse(research_eligible(e,{},1000))
        with self.assertRaises(ValueError):register_snap('unused',MeshSpec(),'unused',e,1000)

    def test_invalid_high_coverage_does_not_displace_feasible_archive(self):
        good=dict(round=1,stage='layers',spec={},native={'case':'good'},research_eligible=True,
                  regional_layers={},evidence=dict(layers={'coverage':.6},quality={'metrics':{'cells':100}}))
        archive=update_archive([],good)
        bad=copy.deepcopy(good);bad['research_eligible']=False;bad['evidence']['layers']['coverage']=.95
        self.assertEqual(update_archive(archive,bad),archive)
        tradeoff=copy.deepcopy(good);tradeoff['evidence']['layers']['coverage']=.7;tradeoff['evidence']['quality']['metrics']['cells']=120
        self.assertEqual(len(update_archive(archive,tradeoff)),2)
        better=copy.deepcopy(good);better['evidence']['layers']['coverage']=.7
        self.assertEqual(len(update_archive(archive,better)),1)

    def test_adaptive_queries_follow_results_and_keep_receipts_through_review(self):
        plan=dict(hypothesis='local snap diagnosis',expected_change='fewer failed boundary faces',
            actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='observed diagonal attraction',evidence=['quality'])])
        payloads=[]
        def http(request,timeout):
            payload=json.loads(request.data);payloads.append(payload);i=len(payloads)
            name='openfoam_reference' if i<=2 else 'propose_mesh_plan'
            args={'topic':'surface_topology'} if i<=2 else plan
            if i==2:self.assertTrue(any('measured-query-1' in m.get('content','') for m in payload['messages']))
            if i==4:self.assertIn('measured-query-1',json.dumps(payload['messages']))
            message=dict(role='assistant',content='',reasoning_content='private fixture',tool_calls=[dict(id=f'call{i}',type='function',function=dict(name=name,arguments=json.dumps(args)))])
            return StringIO(json.dumps(dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=message,finish_reason='tool_calls')])))
        def write(path,data):
            write_json(path,data)
            if Path(path).name.startswith('tool_request_'):
                response=Path(path).with_name(Path(path).name.replace('tool_request_','tool_response_'))
                answer=dict(certification={'ok':True},physical_scales={'height':.001}) if Path(path).stem.endswith('_final') else dict(observation='measured-query-1')
                write_json(response,answer)
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http),patch('cfdmesh.scientific_advisor.write_json',side_effect=write):
            root=Path(tmp);(root/'advisor').mkdir()
            result=scientific_dialogue(root,dict(round=0,evidence={}), 'fake',root/'advisor/usage.json',24,.5,max_turns=6,require_final_preview=True,query_turns=3)
            self.assertEqual(result['decision'],plan);self.assertEqual(result['tool_queries'],2)
            self.assertTrue(result['scientific_review_completed'])
            public=''.join(p.read_text() for p in (root/'advisor').glob('public_answer*.json'))
            self.assertNotIn('private fixture',public)

    def test_insufficient_reserved_turns_rejected(self):
        with self.assertRaises(ValueError):scientific_dialogue('unused',{},'fake','unused',24,.5,max_turns=4,query_turns=2)

    def test_pro_uses_its_billing_and_never_sends_flash_vision_input(self):
        from cfdmesh.scientific_advisor import cached_peak_charge
        plan=dict(hypothesis='bounded hypothesis',expected_change='native test',actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='measured defect',evidence=['quality'])])
        payloads=[]
        def http(request,timeout):
            payloads.append(json.loads(request.data))
            message=dict(role='assistant',content='',tool_calls=[dict(id='p1',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(plan)))])
            return StringIO(json.dumps(dict(model='deepseek-v4-pro',usage=dict(prompt_tokens=1000,completion_tokens=100),choices=[dict(message=message,finish_reason='tool_calls')])))
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http):
            root=Path(tmp);(root/'advisor').mkdir();(root/'input').mkdir()
            (root/'input/geometry.png').write_bytes(b'not an image; text-only actor must not read it')
            answer=scientific_dialogue(root,dict(round=-1,evidence={}), 'fake',root/'advisor/usage.json',24,.5,model='deepseek-v4-pro')
            self.assertEqual(payloads[0]['model'],'deepseek-v4-pro')
            self.assertIsInstance(payloads[0]['messages'][1]['content'],str)
            receipt=answer['receipts'][0]
            self.assertEqual(receipt['requested_model'],'deepseek-v4-pro')
            self.assertAlmostEqual(receipt['usd_at_peak_price_ceiling'],.001716)
            self.assertFalse(receipt['image_input']['attached'])
            self.assertGreater(cached_peak_charge(receipt['usage'],'deepseek-v4-pro'),cached_peak_charge(receipt['usage']))

    def test_compact_evidence_preserves_numeric_controls_and_original(self):
        spec=MeshSpec().to_dict()
        spec['regions']=[dict(name='measured',min=[-.1,.123456789,.3],max=[.4,.5,.6],levels=[{'distance':1,'level':7}],why='long prose'*100,centre=None)]
        original=dict(current_spec=spec,last_tested_spec=copy.deepcopy(spec),spatial=[{'id':'observed','min':[1,2,3]}])
        view=compact_model_evidence(original)
        self.assertEqual(view['current_spec']['regions'][0]['min'],spec['regions'][0]['min'])
        self.assertEqual(view['last_tested_spec'],{'same_as_current_spec':True})
        self.assertEqual(view['spatial'],original['spatial'])
        self.assertIn('why',original['current_spec']['regions'][0])

    def test_large_region_view_is_lossless_and_tested_plan_is_an_exact_delta(self):
        from cfdmesh.scientific_advisor import compact_region_tables
        spec=MeshSpec().to_dict()
        spec['regions']=[dict(name=f'r{i}',shape='box',mode='inside',min=[i*.0123456789,0.,0.],max=[i*.0123456789+.005,1.,1.],levels=[{'distance':1.,'level':6}],why='repeated prose') for i in range(30)]
        last=copy.deepcopy(spec);last['snap']['n_smooth_patch']+=1;last['regions'][0]['levels'][0]['level']=7
        original=dict(current_spec=spec,last_tested_spec=last,spatial=[dict(id='x',min=[0,1,2],cause_status='hypothesis')])
        view=compact_model_evidence(original)
        table=view['current_spec']['regions']
        restored=[{k:v for k,v in zip(table['columns'],row) if v is not None} for row in table['rows']]
        self.assertEqual(restored,[{k:v for k,v in r.items() if k!='why'} for r in spec['regions']])
        delta=view['last_tested_spec']['diff_from_current_spec']
        self.assertEqual(delta['snap'],last['snap'])
        self.assertEqual(delta['regions']['added_or_changed'][0]['levels'][0]['level'],7)
        self.assertEqual(view['spatial_interpretations']['cause_status'],['hypothesis'])
        self.assertEqual(original['spatial'][0]['cause_status'],'hypothesis')
        self.assertLess(len(json.dumps(view)),len(json.dumps(original))*.65)

    def test_program_review_still_requires_compute_preview(self):
        plan=dict(hypothesis='bounded snap hypothesis',expected_change='native test required',actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='observed topology',evidence=['quality'])])
        message=dict(role='assistant',content='',tool_calls=[dict(id='call1',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(plan)))])
        response=dict(model='deepseek-flash',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(message=message,finish_reason='tool_calls')])
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',return_value=StringIO(json.dumps(response))) as http,patch('cfdmesh.scientific_advisor.final_preview',return_value={'certification':{'ok':True}}) as preview:
            root=Path(tmp);(root/'advisor').mkdir()
            answer=scientific_dialogue(root,dict(round=0,evidence={}), 'fake',root/'advisor/usage.json',24,.5,max_turns=6,require_final_preview=True,query_turns=2,require_scientific_review=False)
            self.assertEqual(http.call_count,1);self.assertEqual(preview.call_count,1)
            self.assertFalse(answer['scientific_review_completed'])
            self.assertEqual(answer['final_certified_preview']['certification'],{'ok':True})


if __name__=='__main__':unittest.main()
