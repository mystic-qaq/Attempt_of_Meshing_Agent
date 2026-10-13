import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import trimesh
from cfdmesh.verify import quality_report,read_vtk_centres,boundary_scalar
from cfdmesh.geometry import prepare,fidelity
from cfdmesh.planning import initial_plan,certify,apply_actions,finest_size,rans_target
from cfdmesh.case_builder import render_snappy_hex_mesh_dict
from cfdmesh.io import write_json

GOOD='''Checking mesh
    cells: 1000
    Number of regions: 1 (OK).
    body 120 140 ok (closed singly connected)
    Min volume = 1e-9.
    Max aspect ratio = 10 OK.
    Mesh non-orthogonality Max: 45 average: 6
    Max skewness = 1.2 OK.
Mesh OK.
End
'''


class Gates(unittest.TestCase):
    def test_complete_quality(self):
        self.assertTrue(quality_report(GOOD)['accepted'])

    def test_native_point_fan_warning_preserves_patch_count_but_rejects_topology(self):
        bad=GOOD.replace('body 120 140 ok (closed singly connected)',
            'body 120 140Point 42 uses faces which are not connected through an edge\nThis means that the surface is multiply connected at this point')
        result=quality_report(bad)
        self.assertEqual(result['patches']['body'],120);self.assertFalse(result['accepted'])
        self.assertTrue(result['boundary_disconnected_point_fans'])
        self.assertNotIn('nonempty body boundary absent',result['reasons'])

    def test_shared_body_edge_is_rejected_even_when_native_summary_says_ok(self):
        text=GOOD.replace('body 120 140 ok (closed singly connected)','body 120 140 multiply connected (shared edge)')
        result=quality_report(text)
        self.assertEqual(result['n_failed'],0);self.assertFalse(result['accepted'])
        self.assertTrue(result['body_shared_edge_defect'])

    def test_multiple_time_checks_cannot_certify_final_mesh(self):
        result=quality_report('Time = constant\n'+GOOD+'Time = 2\n'+GOOD)
        self.assertFalse(result['accepted']);self.assertFalse(result['verified'])
        self.assertTrue(quality_report('Time = constant\n'+GOOD)['accepted'])

    def test_truncation_is_not_success(self):
        self.assertFalse(quality_report(GOOD.split('Mesh OK')[0])['verified'])

    def test_unknown_failure_is_rejected(self):
        self.assertFalse(quality_report(GOOD.replace('Mesh OK.','Failed 1 mesh checks.'))['accepted'])

    def test_returncode_is_evidence(self):
        self.assertFalse(quality_report(GOOD,124)['accepted'])

    def test_empty_body_missing_metric_negative_volume(self):
        for text in [GOOD.replace('body 120','body 0'),GOOD.replace('Max skewness','No skewness'),
                     GOOD.replace('1e-9','-1e-9')]:
            self.assertFalse(quality_report(text)['accepted'])

    def test_fatal_metric_native_variant_is_still_measured(self):
        bad=GOOD.replace('Max aspect ratio = 10 OK.','***High aspect ratio cells found, Max aspect ratio: 1e95, number of cells 2')
        bad=bad.replace('Min volume = 1e-9.','***Zero or negative cell volume detected. Minimum negative volume: -1e-7, Number of negative volume cells: 2')
        q=quality_report(bad)
        self.assertEqual(q['metrics']['min_volume'],-1e-7)
        self.assertEqual(q['metrics']['max_aspect'],1e95)
        self.assertFalse(q['accepted'])

    def test_failed_reports_are_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(Path(tmp)/'a.json',dict(report=quality_report('Failed 3 mesh checks.'),value=np.nan))
            value=json.loads((Path(tmp)/'a.json').read_text())
            self.assertIsNone(value['value'])

    def test_standard_vtk_tetra_and_face(self):
        base='# vtk DataFile Version 2.0\nfixture\nASCII\nDATASET UNSTRUCTURED_GRID\nPOINTS 4 float\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.vtk';p.write_text(base+'CELLS 1 5\n4 0 1 2 3\nCELL_TYPES 1\n10\n')
            np.testing.assert_allclose(read_vtk_centres(p),[[.25,.25,.25]])

    def test_binary_boundary_field(self):
        header=b'FoamFile {format binary; arch "LSB;label=32;scalar=64";}\nboundaryField\n{\nbody\n{\ntype calculated;\nvalue nonuniform List<scalar>\n3\n('
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'f';p.write_bytes(header+np.array([5,8,0],dtype='<f8').tobytes()+b');\n}\n}')
            values,_=boundary_scalar(p)
            np.testing.assert_array_equal(values,[5,8,0])

    def test_binary_first_byte_can_be_newline(self):
        raw=np.array([1.234,8],dtype='<f8').tobytes()
        raw=b'\n'+raw[1:]
        header=b'FoamFile {format binary; arch "LSB;label=32;scalar=64";} boundaryField {body {type calculated; value nonuniform List<scalar> 2 ('
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'f';p.write_bytes(header+raw+b');}}')
            values,_=boundary_scalar(p)
            np.testing.assert_array_equal(values,np.frombuffer(raw,dtype='<f8'))

    def test_actual_layers_have_spatial_evidence(self):
        from cfdmesh.verify import layer_report
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'0').mkdir()
            (root/'0/nSurfaceLayers').write_text('boundaryField {body {type calculated; value nonuniform List<scalar> 2 (8 0);}}')
            (root/'0/thickness').write_text('boundaryField {body {type calculated; value nonuniform List<scalar> 2 (.01 0);}}')
            obj=root/'body.obj';obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\n')
            report=layer_report(root,obj,rans_target(1),'')
            self.assertFalse(report['accepted']);self.assertEqual(report['coverage'],.5)
            np.testing.assert_allclose(report['bad_layer_points'],[[1/3,0,1/3]])


class GeometryGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name)
        cls.source=root/'sphere.stl';trimesh.creation.icosphere(subdivisions=2,radius=.5).export(cls.source)
        cls.geom=prepare(cls.source,root/'input',n=512)
        cls.spec,cls.physics=initial_plan(cls.geom,budget=2_000_000,with_layers=True)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_analytic_lfs_all_rays(self):
        self.assertAlmostEqual(np.median(self.geom.solid_half_thickness),.5,delta=.025)
        self.assertEqual(self.geom.audit['inward_ray_coverage'],1)

    def test_scale_invariance_and_physical_distance(self):
        source=Path(self.tmp.name)/'large.stl'
        m=trimesh.creation.icosphere(subdivisions=2,radius=5);m.export(source)
        geom=prepare(source,Path(self.tmp.name)/'large',n=512)
        spec,_=initial_plan(geom,budget=2_000_000)
        self.assertEqual(spec.surface.level_max,self.spec.surface.level_max)
        self.assertAlmostEqual(spec.distance_levels[0].distance/self.spec.distance_levels[0].distance,10,places=4)
        text=render_snappy_hex_mesh_dict(self.spec,'body.stl','body',[2,2,2],'body.eMesh')
        self.assertIn('relativeSizes false;',text)
        self.assertIn('firstLayerThickness',text)

    def test_hard_budget_and_quality_not_relaxed(self):
        self.assertTrue(certify(self.spec,self.geom,2_000_000)['ok'])
        self.assertFalse(certify(self.spec,self.geom,100)['ok'])
        with self.assertRaises(ValueError):
            apply_actions(self.spec,[dict(kind='loosen_quality',why='bad',evidence=['quality'])],self.geom,2_000_000)

    def test_global_refinement_cannot_silently_ignore_local_box(self):
        with self.assertRaisesRegex(ValueError,'unexpected fields'):
            apply_actions(self.spec,[dict(kind='surface_refine',min=[0,0,0],max=[1,1,1],why='local',evidence=['layers'])],self.geom,2_000_000)

    def test_no_mesh_call_when_certification_fails(self):
        from cfdmesh.agent import run_agent
        dest=Path(self.tmp.name)/'blocked_run'
        with patch('cfdmesh.agent.run_round') as native,patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')):
            result=run_agent(self.source,dest,'/not/an/install',budget=100,require_layers=False)
            native.assert_not_called()
            self.assertFalse(result['accepted'])

    def test_native_failure_is_reported_without_none_crash(self):
        from cfdmesh.agent import run_agent
        dest=Path(self.tmp.name)/'failed_run'
        def failed(spec,geometry,case,*args):
            Path(case).mkdir()
            return dict(quality=None,error='native timeout',steps=[])
        with patch('cfdmesh.agent.run_round',side_effect=failed),patch('cfdmesh.runner.command',return_value=({'returncode':0},'Surface is closed. All edges connected to two faces.\nSurface is not self-intersecting\nEnd\n')):
            result=run_agent(self.source,dest,'/not/an/install',require_layers=False)
            self.assertFalse(result['accepted'])
            self.assertIn('native pipeline failed',result['stop_reason'])
            self.assertEqual(len(result['rounds']),1)

    def test_wrong_geometry_fails_fidelity(self):
        wall=Path(self.tmp.name)/'wrong.stl';m=trimesh.creation.icosphere(subdivisions=2,radius=.4);m.export(wall)
        report=fidelity(self.geom,wall,finest_size(self.spec,self.geom),n=512)
        self.assertFalse(report['accepted'])

    def test_wall_function_first_height_uses_cell_centre(self):
        p=rans_target(1)
        computed=p['first_layer_height']*.5*p['estimated_utau']/p['nu']
        self.assertAlmostEqual(computed,50)

    def test_mesher_generates_to_fixed_interpolation_gate(self):
        self.assertEqual(self.spec.quality.min_face_weight,.05)
        self.assertEqual(self.spec.quality.check_min_face_weight,.05)
        text=render_snappy_hex_mesh_dict(self.spec,'body.stl','body',[2,2,2],'body.eMesh')
        self.assertIn('minFaceWeight 0.05;',text)


if __name__=='__main__': unittest.main()
