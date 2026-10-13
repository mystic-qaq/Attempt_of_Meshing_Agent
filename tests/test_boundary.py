import tempfile
import unittest
from pathlib import Path
import numpy as np
from cfdmesh.boundary import observe,polygon_geometry,kernel_point

CUBE='''v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 4 3 2 1
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
'''

class NativePolygons(unittest.TestCase):
    def test_native_closed_cube_area_volume_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'body.obj';p.write_text(CUBE)
            mesh,audit,parent=observe(p)
            self.assertTrue(mesh.is_watertight);self.assertAlmostEqual(mesh.volume,8)
            self.assertAlmostEqual(mesh.area,24);self.assertEqual(len(parent),24)
            self.assertAlmostEqual(polygon_geometry(p)[0].sum(),24)

    def test_real_open_face_and_reversed_orientation_not_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'body.obj'
            for text in (CUBE.replace('f 4 1 5 8\n',''),CUBE.replace('f 4 1 5 8','f 8 5 1 4')):
                p.write_text(text)
                with self.assertRaises(ValueError):observe(p)

    def test_concave_kernel_and_crossing_or_nonstar_rejected(self):
        q=np.array([[0,0],[3,0],[3,1],[1,1],[1,3],[0,3]],float)
        p=kernel_point(q);self.assertTrue(0<p[0]<1 and 0<p[1]<1)
        for q in (np.array([[0,0],[3,0],[3,3],[2,3],[2,1],[1,1],[1,3],[0,3]],float),
                  np.array([[0,0],[2,2],[0,2],[2,0],[3,0]],float)):
            with self.assertRaises(ValueError):kernel_point(q)
