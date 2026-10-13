import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from cfdmesh.io import write_json
from cfdmesh.case_builder import MeshSpec
from cfdmesh.resource_model import fit_full_baseline,adjusted_forecast
from cfdmesh.drivaer import research_eligible


class ResourceModelTest(unittest.TestCase):
    def test_only_completed_same_source_full_counts_calibrate_and_background_is_unscaled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case=root/'round0';(case/'constant/triSurface').mkdir(parents=True)
            surface=case/'constant/triSurface/body.stl';surface.write_text('exact same source')
            geom=SimpleNamespace(path=surface)
            parent=dict(status='failed',source_sha256='source',source_mutated=False)
            row=dict(stage='full',spec=MeshSpec().to_dict(),native=dict(case=str(case),steps=[dict(name='snappyHexMesh',ok=True)]),
                evidence=dict(quality=dict(verified=True,accepted=False,metrics={'cells':1000})))
            write_json(root/'agent_run.json',parent);write_json(case/'record.json',row)
            raw=dict(background=100.,total=10000.)
            with patch('cfdmesh.planning.forecast',return_value=raw):
                calibration=fit_full_baseline(case/'record.json',geom,'source')
                estimate=adjusted_forecast(raw,calibration)
                self.assertAlmostEqual(estimate['total'],1850.)
                self.assertFalse(estimate['resource_guarantee'])
                with self.assertRaisesRegex(ValueError,'same-source'):fit_full_baseline(case/'record.json',geom,'derived clone')
                row['stage']='snap';write_json(case/'record.json',row)
                with self.assertRaisesRegex(ValueError,'full-mesh'):fit_full_baseline(case/'record.json',geom,'source')

    def test_calibration_cannot_accept_a_native_mesh_over_the_budget(self):
        evidence=dict(quality=dict(verified=True,accepted=True,metrics={'cells':1001}),fidelity={'accepted':True})
        self.assertFalse(research_eligible(evidence,{},1000))
        with self.assertRaises(ValueError):adjusted_forecast(dict(background=1.,total=100.),{'factor':.01,'safety_multiplier':2.})


if __name__=='__main__':unittest.main()
