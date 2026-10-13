import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cfdmesh.io import read_json, sha256, write_json
from scripts.freeze_drivaer import freeze


class FrozenProtocol(unittest.TestCase):
    def fixture(self,root):
        prep=root/'preparation';prep.mkdir()
        source=root/'drivaer_410.stl';source.write_text('fixture source')
        seed=prep/'automatic_seed_0.json';seed.write_text('{}\n')
        write_json(prep/'preparation.json',dict(code_sha256='fixture-code',
            smoke=dict(snap_accepted=True,layer_native_complete=True,source_mutated=False),
            inputs=[dict(id='drivaer_410',source=str(source),source_sha256=sha256(source),
                native={'accepted':True},automatic_initial_certification={'ok':True})]))
        return prep,source,seed

    @patch('scripts.freeze_drivaer.code_hash',return_value='fixture-code')
    def test_freeze_binds_seed_and_preserves_budget_history_without_execution(self,_):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);prep,source,seed=self.fixture(root);old=root/'old'
            write_json(old/'api_budget_scope.json',dict(run_roots=[str(old/'runs')],lock_directory=str(old/'locks')))
            with patch('cfdmesh.runner.run_round') as native:
                result=freeze(prep,root/'new',history=old)
            native.assert_not_called()
            self.assertEqual(result['cases'][0]['initial_spec_sha256'],sha256(seed))
            self.assertEqual(result['actor_model'],'deepseek-flash')
            self.assertEqual(read_json(old/'api_budget_scope.json')['run_roots'],[str(old/'runs'),str(root/'new/runs')])
            with self.assertRaises(FileExistsError):freeze(prep,root/'new')

    @patch('scripts.freeze_drivaer.code_hash',return_value='fixture-code')
    def test_changed_source_is_rejected_before_any_experiment_is_created(self,_):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);prep,source,_=self.fixture(root);source.write_text('changed')
            with self.assertRaisesRegex(ValueError,'source or seed changed'):freeze(prep,root/'new')
            self.assertFalse((root/'new').exists())

    @patch('scripts.freeze_drivaer.code_hash',return_value='different-code')
    def test_preparation_cannot_silently_use_different_implementation(self,_):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);prep,_,_=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'implementation changed'):freeze(prep,root/'new')
            self.assertFalse((root/'new').exists())
