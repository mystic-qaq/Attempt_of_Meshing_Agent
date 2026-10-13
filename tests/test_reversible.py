import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import trimesh
from cfdmesh.io import read_json
from cfdmesh.geometry import prepare
from cfdmesh.planning import initial_plan,apply_actions,certify
from cfdmesh.candidates import catalog,best_candidate,plan_id,plan_signature
from cfdmesh.agent import run_agent

class Reversible(unittest.TestCase):
    def test_failed_resume_advice_retains_measured_candidate_without_meshing(self):
        e=dict(accepted=False,quality=dict(verified=True,accepted=True,metrics=dict(cells=100000)),fidelity=dict(accepted=True),layers=dict(available=True,accepted=False,coverage=.72),spatial=[],reasons=['layers insufficient'])
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')),patch('cfdmesh.agent.run_round',return_value={'quality':{'verified':True}}) as native,patch('cfdmesh.agent.evaluate',return_value=e),patch('cfdmesh.render.spatial_image'):
            root=Path(tmp);parent=run_agent(self.source,root/'parent','/unused',max_rounds=1)
            with patch('cfdmesh.agent.request_advice',return_value=(None,{'error':'model exhausted output limit'})):
                r=run_agent(self.source,root/'resume','/unused',max_rounds=1,advisor='deepseek-flash',model_plan=True,resume_from=root/'parent')
            self.assertEqual(native.call_count,1);self.assertEqual(r['rounds'],[])
            self.assertEqual(r['best_provisional_candidate']['plan_id'],parent['best_provisional_candidate']['plan_id'])
            self.assertIn('model exhausted output limit',r['stop_reason'])
            self.assertEqual(read_json(root/'resume/handoff.json')['status'],'diagnostic_mesh_only')
    def test_compact_anchor_and_preview_use_restored_physical_baseline(self):
        from cfdmesh.candidates import compact_catalog
        from cfdmesh.scientific_tools import execute_query
        anchor=self.record(self.s);current=copy.deepcopy(self.s);current.layers.n_grow=2
        c=compact_catalog(catalog([anchor],2000000))
        self.assertEqual(c[0]['layer_parameters'],self.s.to_dict()['layers'])
        actions=[dict(kind='restore_plan',plan_id=plan_id(self.s),why='measured anchor',evidence=['quality']),dict(kind='layer_settings',parameters={'n_grow':1},why='tradeoff',evidence=['layers'])]
        r=execute_query('preview_actions',{'actions':actions},dict(geometry=self.g,spec=current,budget=2000000,evidence={'spatial':[]},plan_history=[anchor]))
        self.assertEqual(r['layer_changes_after_restore']['n_grow'],{'before':0,'after':1})
        self.assertEqual(r['restored_anchor_scales']['requested_layer_stack_metres'],r['physical_scales']['requested_layer_stack_metres'])
    def test_image_transport_is_not_text_but_reasoning_replay_is_budgeted(self):
        from cfdmesh.scientific_advisor import prompt_token_ceiling
        p=dict(messages=[dict(role='user',content=[dict(type='text',text='measured geometry'),dict(type='image_url',image_url={'url':'data:image/png;base64,'+'x'*100000,'detail':'low'})])])
        small=prompt_token_ceiling(p)
        p['messages'][0]['content'][1]['image_url']['url']+='y'*100000
        self.assertEqual(prompt_token_ceiling(p),small);self.assertLess(small,3000)
        p['messages'].append(dict(role='assistant',reasoning_content='r'*10000,content=None))
        self.assertGreater(prompt_token_ceiling(p),small+10000)
    def test_open_input_is_blocked_before_native_or_paid_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'open.stl';m=trimesh.creation.box();m.update_faces(range(len(m.faces)-1));m.export(source)
            with patch('cfdmesh.agent.run_round') as native,patch('cfdmesh.agent.request_advice') as paid,patch('cfdmesh.runner.command') as check:
                r=run_agent(source,root/'run','/unused',advisor='deepseek-flash',model_plan=True)
            native.assert_not_called();paid.assert_not_called();check.assert_not_called()
            self.assertEqual(r['status'],'blocked');self.assertEqual(r['rounds'],[])
            self.assertFalse(read_json(root/'run/input_contract.json')['accepted'])
            self.assertEqual(read_json(root/'run/handoff.json')['status'],'input_blocked')
    def test_invalid_native_thickness_cannot_pass_layer_gate(self):
        import numpy as np
        from cfdmesh.verify import layer_report
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'0').mkdir();(root/'0/nSurfaceLayers').touch();(root/'0/thickness').touch()
            for thickness in (np.array([np.nan,.01]),np.array([-.01,.01])):
                with patch('cfdmesh.verify.boundary_scalar',side_effect=[(np.array([5.,5.]),False),(thickness,False)]),patch('cfdmesh.verify.obj_face_geometry',return_value=(np.array([.01,.99]),np.zeros((2,3)))):
                    r=layer_report(root,root/'unused',dict(expansion_ratio=1.2,estimated_utau=1,nu=1e-5),'')
                self.assertFalse(r['accepted']);self.assertIn('thickness',r['reasons'][0])
    def test_handoff_requires_joint_contract_flow_and_complete_artifact(self):
        from cfdmesh.handoff import handoff
        with tempfile.TemporaryDirectory() as tmp:
            case=Path(tmp);mesh=case/'constant/polyMesh';mesh.mkdir(parents=True)
            e=dict(quality=dict(verified=True,accepted=True),fidelity=dict(accepted=True),layers=dict(accepted=True))
            r=dict(status='completed',accepted=True,source_sha256='source',code_sha256='code',config=dict(require_layers=True),rounds=[dict(accepted=True,native=dict(case=str(case)),evidence=e)])
            self.assertFalse(handoff(r)['ready_for_rans_screened_handoff'])
            for name in ('points','faces','owner','neighbour','boundary'):(mesh/name).write_text('mock topology existence')
            self.assertFalse(handoff(r)['ready_for_rans_screened_handoff'])
            e['flow_probe']=dict(near_wall_probe_accepted=True)
            self.assertTrue(handoff(r)['ready_for_rans_screened_handoff'])
            r['rounds'][0]['native']['native_instrumentation']={'runtime_type':'experimental mover'}
            self.assertFalse(handoff(r)['ready_for_rans_screened_handoff'])
            self.assertEqual(handoff(r)['status'],'experimental_screened_mesh')
            del r['rounds'][0]['native']['native_instrumentation']
            e['quality']['accepted']=False
            self.assertFalse(handoff(r)['ready_for_rans_screened_handoff'])
    def test_native_pre_limit_cohort_requires_all_ranks_and_keeps_zero_ambiguous(self):
        from cfdmesh.native_trace import wall_medial_snapshot
        header='epoch,mesh_point,patch_point,x,y,z,medial_distance,medial_x,medial_y,medial_z,wanted_thickness,extrude_status,projected_ratio,ratio_limit\n'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in (0,1):(root/f'processor{i}').mkdir()
            (root/'processor0/cfdNativeMedialTrace_0.csv').write_text(header+'0,3,1,0,0,0,.01,0,0,.01,.02,1,2,.3\n')
            self.assertFalse(wall_medial_snapshot(root)['available'])
            (root/'processor1/cfdNativeMedialTrace_0.csv').write_text(header+'0,8,2,2,0,0,0,2,0,0,0,0,0,.3\n')
            r=wall_medial_snapshot(root)
            self.assertEqual(r['global_master_moving_wall_points'],2);self.assertEqual(r['zero_native_distances'],1)
            self.assertIn('not wall area',r['limitation'])
            local=wall_medial_snapshot(root,[-1,-1,-1],[1,1,1])
            self.assertEqual(local['points_in_region'],1);self.assertEqual(local['pre_limit_ratio_exceedance_fraction'],1)
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.source=cls.root/'body.stl';trimesh.creation.box().export(cls.source)
        cls.g=prepare(cls.source,cls.root/'input',n=128);cls.s,_=initial_plan(cls.g)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def add(self,s=None):
        return apply_actions(s or self.s,[dict(kind='local_refine',min=[.35,.35,.45],max=[.5,.5,.55],level=self.s.surface.level_max+1,why='measured region',evidence=['geometry'])],self.g,2000000)
    def record(self,s,valid=True,coverage=.72):
        return dict(round=0,spec=s.to_dict(),native=dict(error=None),evidence=dict(quality=dict(verified=True,accepted=valid,metrics=dict(cells=100000,min_volume=1e-8 if valid else -1)),fidelity=dict(accepted=True),layers=dict(coverage=coverage),reasons=[]))
    def test_restore_valid_anchor_then_intervene_without_retaining_bad_boxes(self):
        anchor=self.record(self.s);bad=self.add();bad.layers.n_outer_iter=3
        actions=[dict(kind='restore_plan',plan_id=plan_id(self.s),why='negative cells',evidence=['quality']),dict(kind='layer_settings',parameters=dict(mesh_shrinker='displacementMotionSolver'),why='different displacement mechanism',evidence=['layers'])]
        out=apply_actions(bad,actions,self.g,2000000,plan_history=[anchor])
        self.assertEqual(out.regions,self.s.regions);self.assertEqual(out.quality,self.s.quality)
        self.assertEqual(out.layers.n_outer_iter,1);self.assertEqual(out.layers.first_layer_thickness,self.s.layers.first_layer_thickness)
        for history in ([],[self.record(self.s,False,.99)]):
            with self.assertRaisesRegex(ValueError,'valid anchor'):apply_actions(bad,actions,self.g,2000000,plan_history=history)
        with self.assertRaisesRegex(ValueError,'first'):apply_actions(bad,actions[::-1],self.g,2000000,plan_history=[anchor])
    def test_delete_and_add_region_cannot_reuse_an_existing_identifier(self):
        s=self.add()
        s=apply_actions(s,[dict(kind='local_refine',min=[.15,.15,.45],max=[.25,.25,.55],level=s.surface.level_max+1,why='distinct measured region',evidence=['geometry'])],self.g,2000000)
        removed=s.regions[0].name
        actions=[dict(kind='remove_region',name=removed,why='counterproductive box',evidence=['quality']),dict(kind='local_refine',min=[-.5,-.5,.45],max=[-.35,-.35,.55],level=s.surface.level_max+1,why='another location',evidence=['quality'])]
        out=apply_actions(s,actions,self.g,2000000)
        self.assertEqual(len(out.regions),2);self.assertEqual(len({r.name for r in out.regions}),2)
        self.assertEqual(len(s.regions),2)
    def test_removing_required_detail_region_is_transactionally_rejected(self):
        original=self.g.solid_half_thickness.copy()
        try:
            self.g.solid_half_thickness[:]=.018
            s=copy.deepcopy(self.s);s.max_global_cells=s.max_local_cells=100000000
            s=apply_actions(s,[dict(kind='local_refine',min=[-.51]*3,max=[.51]*3,level=s.surface.level_max+2,why='required small detail',evidence=['geometry'])],self.g,100000000)
            self.assertTrue(certify(s,self.g,100000000)['ok'])
            before=s.to_dict()
            with self.assertRaisesRegex(ValueError,'sampled surface'):apply_actions(s,[dict(kind='remove_region',name=s.regions[0].name,why='remove',evidence=['geometry'])],self.g,100000000)
            self.assertEqual(s.to_dict(),before)
        finally:self.g.solid_half_thickness[:]=original
    def test_invalid_high_coverage_mesh_never_becomes_best_candidate(self):
        good=self.record(self.s);bad=self.record(self.add(),False,.99)
        c=catalog([good,bad],2000000)
        self.assertEqual(best_candidate(c)['plan_id'],plan_id(self.s))
        self.assertFalse(c[1]['eligible_for_restore'])
    def test_explanatory_change_does_not_consume_a_second_native_attempt(self):
        s=self.add();other=copy.deepcopy(s);other.regions[0].why='another explanation'
        self.assertEqual(plan_signature(s),plan_signature(other))
        action=dict(kind='update_region',name=s.regions[0].name,min=s.regions[0].min,max=s.regions[0].max,level=s.regions[0].levels[0].level,why='another explanation',evidence=['layers'])
        e=dict(accepted=False,quality=dict(verified=True,accepted=True,metrics=dict(cells=100000)),fidelity=dict(accepted=True),layers=dict(available=True,accepted=False,coverage=.1),spatial=[],reasons=['layers insufficient'])
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')),patch('cfdmesh.agent.run_round',return_value={'quality':{'verified':True}}) as native,patch('cfdmesh.agent.evaluate',return_value=e),patch('cfdmesh.agent.request_advice',return_value=({'actions':[action]},{})),patch('cfdmesh.render.spatial_image'):
            r=run_agent(self.source,Path(tmp)/'run','/unused',initial_override=s.to_dict(),advisor='deepseek-flash',max_rounds=2)
            self.assertEqual(read_json(Path(tmp)/'run/handoff.json')['status'],'diagnostic_mesh_only')
        self.assertEqual(native.call_count,1);self.assertIn('repeated plan',r['stop_reason'])

if __name__=='__main__':unittest.main()
