import tempfile
import unittest
from pathlib import Path
from cfdmesh.case_builder import MeshSpec
from cfdmesh.layer_design import measure_layer_design
from cfdmesh.drivaer import clear_gain,dominates


class LayerDesignTest(unittest.TestCase):
    def test_coverage_gain_cannot_hide_original_layer_or_stack_loss(self):
        region={'available':True,'regions':{'fixed':{'coverage_ge5':.5}}}
        design=dict(available=True,coverage_original_target=.3,area_below_half_original_stack=.2,coverage_design_proxy=.2)
        baseline=dict(research_eligible=True,coverage=.4,cells=100,coverage_ge1=.8,regional_layers=region,layer_design=design)
        candidate=dict(baseline,coverage=.6,layer_design=dict(design,coverage_original_target=0,area_below_half_original_stack=.8,coverage_design_proxy=0))
        self.assertFalse(clear_gain(candidate,baseline));self.assertFalse(dominates(candidate,baseline))
    def test_full_five_layer_coverage_does_not_imply_original_eight_layer_design(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'0').mkdir()
            (root/'body.obj').write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
            (root/'0/nSurfaceLayers').write_text('boundaryField { body { type calculated; value uniform 5; } }')
            (root/'0/thickness').write_text('boundaryField { body { type calculated; value uniform 0.00586660096; } }')
            spec=MeshSpec();spec.layers.n_surface_layers=5;spec.layers.expansion_ratio=1.08;spec.layers.n_outer_iter=1
            physics=dict(layers=8,first_layer_height=.001,expansion_ratio=1.2)
            measured=measure_layer_design(root,spec,physics)
            self.assertTrue(measured['available']);self.assertEqual(measured['coverage_ge5'],1.)
            self.assertEqual(measured['coverage_original_target'],0.)
            self.assertEqual(measured['coverage_design_proxy'],0.)
            self.assertEqual(measured['area_below_half_original_stack'],1.)
            spec.layers.n_outer_iter=3
            self.assertIsNone(measure_layer_design(root,spec,physics)['coverage_design_proxy'])
