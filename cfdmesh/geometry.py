from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import time
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from .io import sha256, write_json


def _read_tri_surface(path):
    m = trimesh.load(str(path), force="mesh", process=True)
    return np.asarray(m.vertices), np.asarray(m.faces)


def sample(mesh, n=4096, seed=0):
    # Explicit RNG: sample density is independent of input tessellation density.
    rng = np.random.default_rng(seed)
    ids = rng.choice(len(mesh.faces), size=n, p=mesh.area_faces / mesh.area)
    uv = rng.random((n, 2))
    uv[uv.sum(axis=1) > 1] = 1 - uv[uv.sum(axis=1) > 1]
    tri = mesh.triangles[ids]
    pts = tri[:, 0] + uv[:, :1] * (tri[:, 1] - tri[:, 0]) + uv[:, 1:] * (tri[:, 2] - tri[:, 0])
    return pts, mesh.face_normals[ids], ids


def ray_distance(mesh, points, normals, sign, diagonal):
    # rtree BVH broad phase instead of all-rays x all-triangles arrays.
    direction = normals * sign
    eps = max(diagonal * 1e-7, 1e-10)
    result = np.full(len(points), np.inf)
    for start in range(0, len(points), 256):
        p = points[start:start + 256]
        d = direction[start:start + 256]
        origins = p + d * eps
        # Trimesh's origin tolerance can report the launch triangle as a hit.
        # Keep all candidate hits, remove self hits, then take the closest positive hit.
        loc, ray, _ = mesh.ray.intersects_location(origins, d, multiple_hits=True)
        if len(ray):
            dist = np.linalg.norm(loc - p[ray], axis=1)
            good = dist > 2 * eps
            np.minimum.at(result, start + ray[good], dist[good])
    return result


@dataclass
class Geometry:
    mesh: object
    path: str
    source_hash: str
    canonical_hash: str
    points: np.ndarray
    normals: np.ndarray
    solid_half_thickness: np.ndarray
    fluid_gap: np.ndarray
    audit: dict

    @property
    def diagonal(self):
        return float(np.linalg.norm(self.mesh.extents))

    @property
    def longest(self):
        return float(self.mesh.extents.max())

    def local_feature(self, points):
        _, idx = cKDTree(self.points).query(np.atleast_2d(points))
        inward = self.solid_half_thickness[idx]
        outward = self.fluid_gap[idx] * 0.5
        return np.minimum(inward, outward)

    def nearest(self, points):
        return trimesh.proximity.closest_point(self.mesh, np.atleast_2d(points))


def prepare(source, directory, scale=1.0, n=4096,centre_geometry=False):
    t0 = time.monotonic()
    source, directory = Path(source), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    before = sha256(source)
    mesh = trimesh.load(str(source), force="mesh", process=False)
    # No part names, material tags, source STL region names or semantic segmentation.
    # Only vertices/faces survive the canonical export, which has exactly one solid.
    mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=False)
    if scale <= 0 or not np.isfinite(scale):
        raise ValueError("scale-to-metres must be positive")
    mesh.apply_scale(scale)
    mesh.merge_vertices(digits_vertex=12)
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError("empty or non-finite geometry")
    if not mesh.is_watertight:
        raise ValueError("input must be closed and watertight; geometry repair is out of scope")
    winding_normalised=False
    if not mesh.is_winding_consistent:
        if mesh.body_count!=1:raise ValueError('inconsistent multiple-shell input needs enclosure-orientation audit')
        # Topological face reorientation preserves every surface triangle/coordinate.
        # This is not a hole/intersection repair and never touches the source file.
        trimesh.repair.fix_winding(mesh);winding_normalised=True
        if not mesh.is_winding_consistent:raise ValueError('could not establish coherent single-shell winding')
    orientation_reversed=False
    if mesh.volume<0:
        # Reverse a coherent single shell, preserving every vertex and triangle.
        # Mixed/nested component conventions require a separate enclosure audit.
        if mesh.body_count!=1:raise ValueError('inward multiple-shell input needs enclosure-orientation audit')
        mesh.invert();orientation_reversed=True
    if mesh.volume<=0:raise ValueError('input has nonpositive enclosed volume')
    if (mesh.area_faces <= 1e-20).any():
        raise ValueError("degenerate triangles must be repaired upstream")
    original_bounds=mesh.bounds.copy();origin=mesh.bounds.mean(axis=0) if centre_geometry else np.zeros(3)
    inverse_error=0.
    if centre_geometry:
        original_vertices=mesh.vertices.copy();mesh.apply_translation(-origin)
        inverse_error=float(np.max(np.abs(mesh.vertices+origin-original_vertices)))
    canonical = directory / "body.stl"
    canonical.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    # Reload exported float32 triangles so every later metric uses exactly mesher input.
    original_mesh=mesh
    mesh = trimesh.load(str(canonical), force="mesh", process=False);mesh.merge_vertices(digits_vertex=12)
    binary_roundtrip_max_coordinate_error=0.
    if len(mesh.faces)!=len(original_mesh.faces):binary_roundtrip_max_coordinate_error=float('inf')
    else:
        for begin in range(0,len(mesh.faces),16384):
            old=original_mesh.vertices[original_mesh.faces[begin:begin+16384]]
            new=mesh.vertices[mesh.faces[begin:begin+16384]]
            binary_roundtrip_max_coordinate_error=max(binary_roundtrip_max_coordinate_error,float(np.abs(old-new).max()))
    roundoff=64*np.finfo(float).eps*max(1.,float(np.abs(original_mesh.vertices).max()))
    if binary_roundtrip_max_coordinate_error>roundoff or not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume<=0 or np.any(mesh.area_faces<=1e-20):
        canonical.write_text(trimesh.exchange.stl.export_stl_ascii(original_mesh))
        mesh=trimesh.load(str(canonical),force='mesh',process=False);mesh.merge_vertices(digits_vertex=12)
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume<=0 or np.any(mesh.area_faces<=1e-20):
            raise ValueError('canonical double precision surface lost input topology')
    points, normals, _ = sample(mesh, n=n)
    diagonal = float(np.linalg.norm(mesh.extents))
    inward = ray_distance(mesh, points, normals, -1, diagonal) * 0.5
    outward = ray_distance(mesh, points, normals, 1, diagonal)
    finite = np.isfinite(inward)
    if finite.mean() < 0.99:
        raise ValueError("closed-surface inward ray coverage below 99%; orientation/intersection unresolved")
    values = np.minimum(inward, outward * 0.5)
    # No proximity substitution for unmeasured rays. All rays were attempted.
    qs = {f"p{q}": float(np.percentile(values[np.isfinite(values)], q)) for q in (1, 5, 10, 25, 50, 90)}
    audit = dict(source=str(source), source_sha256=before,
                 canonical_sha256=sha256(canonical), scale_to_metres=scale,
                 coordinate_frame=("bbox-centred origin, source axes, physical metres; flow +X, vertical +Z" if centre_geometry else "source axes, physical metres; flow +X, vertical +Z"),
                 rigid_origin_conditioning=dict(enabled=bool(centre_geometry),original_scaled_bbox=original_bounds,
                     source_origin_metres=origin,source_to_agent_translation_metres=-origin,
                     inverse_coordinate_max_error_metres=inverse_error,shape_repair=False),
                 semantic_parts_used=False, triangles=len(mesh.faces), vertices=len(mesh.vertices),
                 coherent_single_shell_orientation_reversed=orientation_reversed,
                 single_shell_winding_normalised=winding_normalised,
                 canonical_precision='ASCII float64' if canonical.read_bytes()[:5]==b'solid' else 'binary float32',
                 binary_roundtrip_max_coordinate_error_metres=binary_roundtrip_max_coordinate_error,
                 watertight=bool(mesh.is_watertight), winding_consistent=bool(mesh.is_winding_consistent),
                 area=float(mesh.area), volume=float(mesh.volume), bbox=mesh.bounds,
                 extents=mesh.extents, diagonal=diagonal,
                 feature_half_size=qs, measurement="bidirectional triangle-BVH normal rays",
                 sample_seed=0, samples=n, inward_ray_coverage=float(finite.mean()),
                 finite_fluid_gap_fraction=float(np.isfinite(outward).mean()),
                 self_intersection="unavailable_until_native_surfaceCheck",
                 source_mutated=(sha256(source) != before), seconds=time.monotonic()-t0)
    write_json(directory / "audit.json", audit)
    np.savez_compressed(directory / "probe.npz", points=points, normals=normals,
                        inward=inward, outward=outward)
    return Geometry(mesh, str(canonical), before, sha256(canonical), points,
                    normals, inward, outward, audit)


def fidelity(geom, wall_surface, finest, n=8192):
    from .boundary import observe
    try:wall,observer,_=observe(wall_surface)
    except ValueError as e:
        return {"available":False,"accepted":False,"reasons":["native boundary observation unavailable: "+str(e)]}
    return fidelity_on_surface(geom,wall,finest,n,observer)


def fidelity_on_surface(geom,wall,finest,n=8192,observer=None):
    """Identical sampled gates for an independently verified observed surface.

    Callers must establish provenance and native self-intersection evidence;
    watertightness alone does not certify either property.
    """
    if not wall.is_watertight or not wall.is_winding_consistent or np.any(wall.area_faces<=0):
        return dict(available=False,accepted=False,reasons=['observed triangles fail closure/orientation/area'])
    original_pts, _, _ = sample(geom.mesh, n=n, seed=71)
    wall_pts, _, _ = sample(wall, n=n, seed=72)
    _, d1, _ = trimesh.proximity.closest_point(wall, original_pts)
    _, d2, _ = trimesh.proximity.closest_point(geom.mesh, wall_pts)
    p99 = float(max(np.percentile(d1, 99), np.percentile(d2, 99)))
    threshold = min(1.5 * finest, 0.005 * geom.longest)
    v_err = abs(abs(wall.volume) - geom.mesh.volume) / geom.mesh.volume
    a_err = abs(wall.area - geom.mesh.area) / geom.mesh.area
    # Feature-local error: protects narrow details that a global bbox test misses.
    feature = geom.local_feature(original_pts)
    resolved = np.isfinite(feature) & (feature > 1e-10)
    relative = d1[resolved] / feature[resolved]
    local_bad_fraction = float(np.mean(relative > 0.25)) if len(relative) else None
    reasons = []
    if p99 > threshold:
        reasons.append("bidirectional boundary p99 distance exceeds geometric tolerance")
    if v_err > 0.02:
        reasons.append("body volume error exceeds 2%")
    if a_err > 0.10:
        reasons.append("body area error exceeds 10%")
    if local_bad_fraction is None or local_bad_fraction > 0.02:
        reasons.append("more than 2% sampled surface violates local-feature error tolerance")
    bad = original_pts[(d1 > threshold) | (resolved & (d1 > 0.25 * feature))]
    return dict(available=True, accepted=not reasons, reasons=reasons,
                bidirectional_distance_p99=p99, distance_tolerance=threshold,
                volume_relative_error=float(v_err), area_relative_error=float(a_err),
                local_feature_bad_fraction=local_bad_fraction, samples_per_surface=n,
                limitations="sampled geometric fidelity; not a Hausdorff guarantee or flow accuracy",
                bad_surface_points=bad[:4096].tolist(), wall_triangles=len(wall.faces),boundary_observer=observer)
