import json
import tempfile
import unittest
from pathlib import Path
from cfdmesh.case_builder import MeshSpec
from cfdmesh.io import write_json
from cfdmesh.decision_checkpoint import visible_queries
from cfdmesh.scientific_advisor import commitment_messages,compact_model_evidence


class DecisionCheckpointTest(unittest.TestCase):
    def test_checkpoint_reuses_only_complete_same_source_flash_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=MeshSpec();(root/'advisor').mkdir()
            state=dict(status='failed',source_sha256='source',source_mutated=False,profile={'model':'deepseek-flash'},rounds=[])
            write_json(root/'agent_run.json',state)
            write_json(root/'advisor/request_-1.json',dict(request_id='centred',evidence={'current_spec':spec.to_dict()}))
            call=dict(id='q1',type='function',function=dict(name='inspect_cluster',arguments=json.dumps({'id':'measured:1'})))
            missing=dict(id='q2',type='function',function=dict(name='inspect_cluster',arguments=json.dumps({'id':'unavailable:2'})))
            write_json(root/'advisor/public_answer_-1_0.json',dict(content='',tool_calls=[call,missing]))
            write_json(root/'advisor/tool_request_-1_0_0.json',dict(name='inspect_cluster',arguments={'id':'measured:1'}))
            write_json(root/'advisor/tool_response_-1_0_0.json',dict(count=3,min=[.123456789,0.,1.]))
            result=visible_queries(root,'source',spec,'centred')
            self.assertEqual(result['messages'][1]['tool_call_id'],'q1')
            self.assertEqual(result['unavailable_calls'][0]['tool_call_id'],'q2')
            self.assertEqual(len(result['messages'][0]['tool_calls']),1)
            self.assertEqual(json.loads(result['messages'][1]['content'])['min'][0],.123456789)
            with self.assertRaisesRegex(ValueError,'geometry'):visible_queries(root,'source',spec,'clone')
            state['profile']['model']='deepseek-v4-pro';write_json(root/'agent_run.json',state)
            with self.assertRaisesRegex(ValueError,'Flash'):visible_queries(root,'source',spec,'centred')

    def test_final_view_keeps_exact_controls_receipts_and_excludes_private_thought(self):
        spec=MeshSpec().to_dict();spec['regions']=[dict(name=f'r{i}',shape='box',min=[i,0,0],max=[i+1,1,1],levels=[{'distance':1,'level':6}]) for i in range(100)]
        evidence=compact_model_evidence(dict(current_spec=spec,spatial=[dict(id='target',min=[.123456789,0,0])],budget=12000000))
        messages=[dict(role='assistant',content='',reasoning_content='private fixture',tool_calls=[]),dict(role='tool',tool_call_id='q1',content=json.dumps({'measured_gap_metres':.0123456789}))]
        view=commitment_messages(evidence,messages);text=json.dumps(view)
        self.assertNotIn('private fixture',text)
        self.assertIn('.0123456789',text);self.assertIn('.123456789',text)
        self.assertNotIn('"r99"',text)
        self.assertIn('12000000',text)

    def test_spooled_checkpoint_enters_bounded_final_call_without_another_paid_query(self):
        from contextlib import nullcontext
        from io import StringIO
        from unittest.mock import patch
        from cfdmesh.scientific_advisor import scientific_dialogue
        plan=dict(hypothesis='measured repair',expected_change='native validation',actions=[dict(kind='snap_settings',parameters={'avoid_diagonal':True},why='measured issue',evidence=['quality'])])
        payloads=[]
        def http(request,timeout):
            payloads.append(json.loads(request.data))
            msg=dict(role='assistant',content='',tool_calls=[dict(id='final',type='function',function=dict(name='propose_mesh_plan',arguments=json.dumps(plan)))])
            return StringIO(json.dumps(dict(model='deepseek-flash',usage=dict(prompt_tokens=1000,completion_tokens=100),choices=[dict(message=msg,finish_reason='tool_calls')])))
        checkpoint=dict(messages=[dict(role='assistant',content='Completed measured queries; commit now.')])
        with tempfile.TemporaryDirectory() as tmp,patch('cfdmesh.scientific_advisor.ledger_lock',lambda _:nullcontext()),patch('cfdmesh.scientific_advisor.urllib.request.urlopen',side_effect=http):
            root=Path(tmp);(root/'advisor').mkdir()
            result=scientific_dialogue(root,dict(round=-1,evidence={'resume_visible_queries':checkpoint}),'fake',root/'advisor/usage.json',24,.009,max_output=8192)
            self.assertEqual(result['decision'],plan)
            self.assertEqual(payloads[0]['thinking'],{'type':'disabled'})
            self.assertEqual(payloads[0]['tool_choice']['function']['name'],'propose_mesh_plan')
            self.assertGreaterEqual(payloads[0]['max_tokens'],1024)
            self.assertLess(payloads[0]['max_tokens'],4096)
            self.assertLessEqual(result['receipts'][0]['reserved_usd'],.009)


if __name__=='__main__':unittest.main()
