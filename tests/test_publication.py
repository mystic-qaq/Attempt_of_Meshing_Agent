import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.export_portfolio import export


class Publication(unittest.TestCase):
    def fixture(self,root):
        src=root/'source';src.mkdir()
        for name in ('README.md','NOTICE.md','LICENSE','pyproject.toml','.gitignore','.gitattributes','requirements-v4.txt'):(src/name).write_text('initial content\n')
        (src/'scripts').mkdir()
        for name in ('export_portfolio.py','native_gap_smoke.py','measure_gap_smoke.py','drivaer_visualize.py'):(src/'scripts'/name).write_text('# fixture\n')
        return src

    def test_managed_update_keeps_auditable_hashes_and_refuses_user_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=self.fixture(root);dest=root/'published';export(src,dest)
            (src/'README.md').write_text('new approved source\n');export(src,dest,update=True)
            m=json.loads((dest/'PUBLICATION_MANIFEST.json').read_text())
            self.assertTrue(all(hashlib.sha256((dest/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in m['files']))
            (dest/'README.md').write_text('user edits\n')
            with self.assertRaisesRegex(ValueError,'user edits'):export(src,dest,update=True)
            self.assertEqual((dest/'README.md').read_text(),'user edits\n')

    def test_secret_or_source_mesh_cannot_enter_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=self.fixture(root);(src/'cfdmesh').mkdir()
            (src/'cfdmesh/bad.py').write_text('credential = "sk-" + "placeholder"\n')
            (src/'cfdmesh/bad.py').write_text('sk-'+('x'*24))
            with self.assertRaisesRegex(ValueError,'scan failed'):export(src,root/'bad')
            self.assertFalse((root/'bad').exists())
            (src/'cfdmesh/bad.py').write_text('# clean\n');(src/'assets').mkdir();(src/'assets/body.stl').write_text('solid private geometry')
            with self.assertRaisesRegex(ValueError,'prohibited'):export(src,root/'bad')
            self.assertFalse((root/'bad').exists())

    def test_export_includes_focused_study_drivers_and_native_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=self.fixture(root)
            evidence=src/'results/drivaer_focus_20261012/FINAL_EVIDENCE.json'
            evidence.parent.mkdir(parents=True);evidence.write_text('{"qualified_campaign_candidates":0}\n')
            driver=src/'scripts/drivaer_study_report.py';driver.write_text('# study driver\n')
            native=src/'native_tools/cgal_surface_audit.cpp'
            native.parent.mkdir();native.write_text('// native source\n')
            checks=src/'results/publication_20261013/software_checks.log'
            checks.parent.mkdir(parents=True);checks.write_text('OK\n')
            dest=root/'published';export(src,dest)
            for item in (evidence,driver,native,checks):
                self.assertEqual((dest/item.relative_to(src)).read_bytes(),item.read_bytes())


if __name__=='__main__':unittest.main()
