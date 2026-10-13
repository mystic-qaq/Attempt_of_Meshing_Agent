import tempfile
import unittest
from pathlib import Path
from cfdmesh.io import sha256
from cfdmesh.surface_contract import composite_surface_report


class IndependentSourceTest(unittest.TestCase):
    def test_disagreement_keeps_native_report_and_requires_complete_hash_bound_proof(self):
        text='Surface is closed. All edges connected to two faces.\nSurface is self-intersecting at 1 locations\nEnd\n'
        with tempfile.TemporaryDirectory() as tmp:
            surface=Path(tmp)/'source.stl';surface.write_bytes(b'unchanged fixture')
            proof=dict(kind='CGAL 5.6.2 EPICK source audit',source_sha256=sha256(surface),source_mutated=False,returncode=0,
                result=dict(accepted=True,valid_polygon_mesh=True,closed=True,self_intersecting=False,outward=True,components=1,degenerate_triangles=0,faces=12,volume=1.))
            self.assertFalse(composite_surface_report(text,0,surface)['accepted'])
            result=composite_surface_report(text,0,surface,proof)
            self.assertTrue(result['accepted']);self.assertTrue(result['disagreement'])
            self.assertFalse(result['native_report']['accepted'])
            self.assertFalse(composite_surface_report(text.replace('End',''),0,surface,proof)['accepted'])
            proof['result']['self_intersecting']=True
            self.assertFalse(composite_surface_report(text,0,surface,proof)['accepted'])
            proof['result']['self_intersecting']=False;surface.write_bytes(b'different geometry')
            self.assertFalse(composite_surface_report(text,0,surface,proof)['accepted'])
