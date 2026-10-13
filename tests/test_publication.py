import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.audit_repository import audit


class Publication(unittest.TestCase):
    def fixture(self,root):
        study=root/'results/drivaer';study.mkdir(parents=True)
        evidence=study/'evidence.json'
        evidence.write_text(json.dumps(dict(runs=[],campaign_native_attempts=0,eligible_native_campaign_attempts=0)),encoding='utf-8')
        (study/'manifest.json').write_text(json.dumps({'files':[dict(path='evidence.json',sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())]}),encoding='utf-8')

    def test_credentials_and_source_mesh_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.fixture(root);(root/'cfdmesh').mkdir()
            secret=root/'cfdmesh/bad.py';secret.write_text('sk-'+('x'*24),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'scan failed'):audit(root)
            secret.write_text('# clean\n',encoding='utf-8');(root/'results/drivaer/body.stl').write_text('solid source')
            with self.assertRaisesRegex(ValueError,'prohibited artifact'):audit(root)

    def test_legacy_documents_and_broken_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.fixture(root);(root/'docs').mkdir()
            old=root/'docs/AGENT_GUIDE.zh-CN.md';old.write_text('personal guide\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'obsolete document'):audit(root)
            old.unlink();(root/'README.md').write_text('[missing](docs/missing.md)\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'broken local link'):audit(root)

    def test_changed_evidence_and_hidden_stages_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.fixture(root);self.assertEqual(audit(root),2)
            path=root/'results/drivaer/evidence.json';data=json.loads(path.read_text(encoding='utf-8'))
            data['campaign_native_attempts']=1;path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'stage count'):audit(root)
            data['campaign_native_attempts']=0;data['collection']='changed';path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):audit(root)
