import tempfile
import unittest
from pathlib import Path
from cfdmesh.io import write_json,sha256
from cfdmesh.case_builder import MeshSpec
from cfdmesh.stage_evidence import load_stage_comparison


class StageEvidenceTest(unittest.TestCase):
    def test_comparison_requires_same_geometry_and_snap_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths=[];spec=MeshSpec()
            for name,stage,failed in [('before','snap',0),('after','full',6)]:
                run=root/name;case=run/'round0';(case/'constant/triSurface').mkdir(parents=True)
                (case/'constant/triSurface/body.stl').write_text('same centred source')
                write_json(run/'agent_run.json',dict(status='failed',source_sha256='original',source_mutated=False))
                path=case/'record.json';paths.append(path)
                write_json(path,dict(stage=stage,spec=spec.to_dict(),native={'case':str(case)},research_eligible=False,
                    evidence=dict(quality=dict(verified=True,n_failed=failed,accepted=False),layers={'coverage':.3 if failed else None})))
            digest=sha256(paths[0].parent/'constant/triSurface/body.stl')
            receipt=load_stage_comparison(*paths,'original',digest)
            self.assertEqual(receipt['before_layers']['quality']['n_failed'],0)
            self.assertEqual(receipt['after_layers']['quality']['n_failed'],6)
            with self.assertRaisesRegex(ValueError,'same-source'):load_stage_comparison(*paths,'clone',digest)
            import json
            after=json.loads(paths[1].read_text());after['spec']['snap']['n_smooth_patch']+=1;write_json(paths[1],after)
            with self.assertRaisesRegex(ValueError,'different snap'):load_stage_comparison(*paths,'original',digest)


if __name__=='__main__':unittest.main()
