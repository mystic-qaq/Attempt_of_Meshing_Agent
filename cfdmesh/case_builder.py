"""Build a complete, runnable snappyHexMesh case from a typed specification.

The spec is the *only* thing the agent is allowed to change.  Everything that
snappyHexMesh needs but that is not a meshing decision (fvSchemes, fvSolution,
controlDict, meshQualityDict defaults) is materialised from the version-matched
OpenFOAM installation so the case is always self-consistent.

Design note: the agent's action space deliberately contains *region* objects
(``RefinementRegion``) in addition to global scalars.  Region-based action is what
makes a targeted fix possible instead of blind global tuning.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np


# ======================================================================================
# specification
# ======================================================================================

@dataclass
class DomainSpec:
    """Background mesh / outer domain.

    ``mode='box'``     : symmetric wind-tunnel box (works for any orientation).
    ``mode='tunnel'``  : inlet/outlet/sides along ``axis`` (external aero style).
    ``padding``        : multiples of the body bounding-box diagonal, per side
                         (up, down, sides, downstream, upstream).
    ``base_cells``     : background cell count along the longest body dimension.
                         This is the master knob for total cell budget.
    """

    mode: Literal["box", "tunnel"] = "box"
    # Padding in units of the body bounding-box diagonal.  These are chosen so the
    # *background* mesh stays cheap: the volume of the domain divided by base_cells^3 is
    # the cell count before any refinement, and generous padding multiplies it fast.
    # (An earlier default of 5-8 diagonals with 24 base cells gave a ~14 million cell
    # background mesh, which blockMesh then had to build for every single round.)
    padding_up: float = 3.0
    padding_down: float = 2.0
    padding_side: float = 2.5
    padding_upstream: float = 2.5
    padding_downstream: float = 5.0
    base_cells: int = 16
    grading: float = 1.0
    axis: int = 0

    def validate(self) -> None:
        if self.mode not in {"box", "tunnel"}:
            raise ValueError(f"bad domain mode {self.mode!r}")
        if self.base_cells < 2:
            raise ValueError("base_cells must be >= 2")
        if min(self.padding_up, self.padding_down, self.padding_side,
               self.padding_upstream, self.padding_downstream) <= 0:
            raise ValueError("all paddings must be > 0")


@dataclass
class DistanceLevel:
    """Refine within distance in physical model units (metres after canonical export)."""
    distance: float
    level: int


@dataclass
class RefinementRegion:
    """A spatial refinement region.  This is the agent's local action tool.

    ``shape='box'``    : ``min``/``max`` (model units)
    ``shape='sphere'`` : ``centre`` + ``radius`` (model units)
    ``mode``           : 'inside' | 'outside' | 'distance'
    ``levels``         : list of ``DistanceLevel`` for mode='distance', otherwise one entry
    ``why``            : free-text rationale recorded in the trace (audit trail)
    """
    name: str
    shape: Literal["box", "sphere"]
    mode: Literal["inside", "outside", "distance"]
    levels: list[DistanceLevel]
    min: list[float] | None = None
    max: list[float] | None = None
    centre: list[float] | None = None
    radius: float | None = None
    why: str = ""
    gap_level: list[int] | None = None
    gap_mode: str = "outside"

    def validate(self) -> None:
        if self.gap_level is not None:
            if self.shape != 'box' or self.mode != 'inside' or len(self.gap_level) != 3:
                raise ValueError('gap refinement requires an inside box and three integers')
            if any(isinstance(v,bool) or not isinstance(v,int) for v in self.gap_level):
                raise ValueError('gap refinement labels must be integers')
            cells,start,end=self.gap_level
            if not 3 <= cells <= 8 or not 0 <= start <= end <= 11 or self.gap_mode != 'outside':
                raise ValueError('gap refinement requires 3..8 cells, ordered levels and outside mode')
        if self.shape == "box":
            if self.min is None or self.max is None:
                raise ValueError(f"region {self.name}: box needs min/max")
            if any(b <= a for a, b in zip(self.min, self.max)):
                raise ValueError(f"region {self.name}: min must be < max on every axis")
        elif self.shape == "sphere":
            if self.centre is None or not self.radius or self.radius <= 0:
                raise ValueError(f"region {self.name}: sphere needs centre and radius>0")
        else:
            raise ValueError(f"region {self.name}: bad shape {self.shape!r}")
        if not self.levels:
            raise ValueError(f"region {self.name}: needs at least one level")
        if self.mode == "distance":
            d = [lv.distance for lv in self.levels]
            if any(d[i] >= d[i + 1] for i in range(len(d) - 1)):
                raise ValueError(f"region {self.name}: distance levels must be increasing")
        elif len(self.levels) != 1:
            raise ValueError(f"region {self.name}: mode {self.mode!r} takes exactly one level")
        if any(lv.level < 0 for lv in self.levels):
            raise ValueError(f"region {self.name}: negative refinement level")


@dataclass
class SurfaceRefinement:
    """Per-surface refinement levels and patch info."""
    name: str = "body"
    # The agent may refine the surface anisotropically over space using the
    # 'level (min max)' form; per-region levels are expressed as RefinementRegion.
    level_min: int = 3
    level_max: int = 5
    patch_type: str = "wall"
    patch_group: str = "bodyGroup"

    def validate(self) -> None:
        if self.level_min < 0 or self.level_max < self.level_min:
            raise ValueError("need 0 <= level_min <= level_max")


@dataclass
class FeatureSpec:
    enabled: bool = True
    level: int = 4
    included_angle: float = 150.0
    open_edges: bool = True
    non_manifold_edges: bool = False

    def validate(self) -> None:
        if self.enabled and self.level < 0:
            raise ValueError("feature level must be >= 0")


@dataclass
class SnapSpec:
    n_smooth_patch: int = 3
    tolerance: float = 2.0
    n_solve_iter: int = 30
    n_relax_iter: int = 5
    n_feature_snap_iter: int = 10
    implicit_feature_snap: bool = False
    explicit_feature_snap: bool = True
    n_face_split_interval: int = -1
    avoid_diagonal: bool = False
    concave_angle: float = 45.0
    min_area_ratio: float = 0.3

    def validate(self):
        if isinstance(self.n_face_split_interval,bool) or not isinstance(self.n_face_split_interval,int) or self.n_face_split_interval==0 or self.n_face_split_interval < -1:
            raise ValueError('face splitting interval must be -1 or a positive integer')
        if self.n_face_split_interval>self.n_feature_snap_iter:
            raise ValueError('face splitting interval exceeds feature snapping iterations')
        if not 0 < self.concave_angle <= 90 or not 0 < self.min_area_ratio < 1:
            raise ValueError('invalid face splitting geometry controls')


@dataclass
class LayerSpec:
    enabled: bool = False
    n_surface_layers: int = 3
    first_layer_thickness: float = 0.0
    expansion_ratio: float = 1.2
    final_layer_thickness: float = 0.4       # relative to local surface cell size
    min_thickness: float = 0.1
    feature_angle: float = 60.0
    n_grow: int = 0
    max_face_thickness_ratio: float = 0.5
    max_thickness_to_medial_ratio: float = 0.3
    min_medial_axis_angle: float = 90.0
    n_smooth_thickness: int = 10
    n_smooth_surface_normals: int = 1
    n_smooth_normals: int = 3
    n_relax_iter: int = 3
    n_layer_iter: int = 50
    slip_feature_angle: float = 30.0
    n_buffer_cells_no_extrude: int = 0
    mesh_shrinker: str = 'displacementMedialAxis'
    merge_patch_faces_angle: float = 45.0
    n_outer_iter: int = 1
    layer_termination_angle: float | None = None
    detect_extrusion_island: bool = False

    def validate(self) -> None:
        if self.enabled:
            if self.n_surface_layers < 1:
                raise ValueError("n_surface_layers must be >= 1 when layers are enabled")
            if self.expansion_ratio < 1.0:
                raise ValueError("expansion_ratio must be >= 1")
            if not (0 < self.min_thickness < 1):
                raise ValueError("min_thickness must be in (0,1) for relativeSizes")
            if not (0 < self.final_layer_thickness < 1):
                raise ValueError("final_layer_thickness must be in (0,1)")
            if self.mesh_shrinker not in ('displacementMedialAxis','displacementMotionSolver'):
                raise ValueError('unsupported layer mesh shrinker')
            if not 1 <= self.n_outer_iter <= 5:
                raise ValueError('layer outer iterations must be 1..5')
            if self.layer_termination_angle is not None and not -180 <= self.layer_termination_angle <= 180:
                raise ValueError('invalid layer termination angle')


@dataclass
class QualitySpec:
    """snappyHexMesh meshQualityControls *and* the independent checkMesh thresholds.

    Keeping these separate is deliberate: snap-time limits decide what the mesher
    tolerates while it works; check-time limits decide what we accept afterwards.
    """
    # snap-time
    max_non_ortho: float = 65.0
    max_boundary_skewness: float = 4.0
    max_internal_skewness: float = 4.0
    max_concave: float = 80.0
    min_vol: float = 1e-13
    min_tet_quality: float = 1e-15
    min_area: float = -1.0
    min_twist: float = 0.02
    min_determinant: float = 0.001
    min_face_weight: float = 0.02
    min_vol_ratio: float = 0.01
    min_triangle_twist: float = -1.0
    n_smooth_scale: int = 4
    error_reduction: float = 0.75

    # check-time acceptance (solver-agnostic defaults; a solver profile overrides)
    check_max_non_ortho: float = 70.0
    check_max_skewness: float = 4.0
    check_max_aspect_ratio: float = 1000.0
    check_max_boundary_skewness: float = 20.0
    check_min_face_weight: float = 0.05
    check_min_vol_ratio: float = 0.01
    check_max_concave: float = 80.0
    check_max_cell_openness: float = 1.0

    def validate(self) -> None:
        if not (0 < self.max_non_ortho <= 90):
            raise ValueError("max_non_ortho must be in (0,90]")
        for nm, v in (("min_twist", self.min_twist), ("min_determinant", self.min_determinant),
                      ("min_face_weight", self.min_face_weight),
                      ("min_vol_ratio", self.min_vol_ratio)):
            if nm == "min_twist":
                continue
            if v <= 0:
                raise ValueError(f"{nm} must be > 0")


@dataclass
class MeshSpec:
    """The complete, serialisable meshing plan."""
    cell_size_target: float = 0.0    # model units; 0 = derive from levels
    surface: SurfaceRefinement = field(default_factory=SurfaceRefinement)
    domain: DomainSpec = field(default_factory=DomainSpec)
    distance_levels: list[DistanceLevel] = field(default_factory=list)
    regions: list[RefinementRegion] = field(default_factory=list)
    features: FeatureSpec = field(default_factory=FeatureSpec)
    snap: SnapSpec = field(default_factory=SnapSpec)
    layers: LayerSpec = field(default_factory=LayerSpec)
    quality: QualitySpec = field(default_factory=QualitySpec)
    max_global_cells: int = 20_000_000
    max_local_cells: int = 2_000_000
    min_refinement_cells: int = 10
    n_cells_between_levels: int = 3
    resolve_feature_angle: float = 30.0
    allow_free_standing_zone_faces: bool = True
    merge_tolerance: float = 1e-6
    location_in_mesh: list[float] | None = None   # None -> auto-detect
    # "binary" cuts mesh I/O by roughly an order of magnitude versus ascii, and the
    # planner never reads the mesh textually -- it reads the checkMesh report and the
    # bad-cell sets.  On a 12M-cell mesh the difference is minutes per round.
    write_format: str = "binary"
    rationale: str = ""

    def validate(self) -> None:
        self.surface.validate()
        self.domain.validate()
        self.features.validate()
        self.snap.validate()
        self.layers.validate()
        self.quality.validate()
        for r in self.regions:
            r.validate()
        # cell_size_target is an optional convenience field only; the authoritative
        # sizing comes from domain.base_cells + surface.level_max, and a mesh plan built
        # purely from those two is perfectly valid (this is how the planner works).
        if self.cell_size_target < 0:
            raise ValueError("cell_size_target must be >= 0")
        if self.surface.level_max > 12:
            raise ValueError("surface.level_max > 12 is not a sane meshing plan")
        if self.n_cells_between_levels < 1:
            raise ValueError("n_cells_between_levels must be >= 1")
        if self.allow_free_standing_zone_faces and self.features.enabled:
            # Known OpenFOAM abort: mergeFreeStandingBaffles -> findDuplicateFaces
            # when explicit feature edges sit exactly on a background-mesh face plane.
            # Guarded here so the agent cannot trip it by accident.
            raise ValueError(
                "allow_free_standing_zone_faces=true together with explicit features "
                "can abort snappyHexMesh in mergeFreeStandingBaffles; set it false "
                "unless you have a specific reason")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MeshSpec":
        d = dict(d)
        d["surface"] = SurfaceRefinement(**d.get("surface", {}))
        d["domain"] = DomainSpec(**d.get("domain", {}))
        d["features"] = FeatureSpec(**d.get("features", {}))
        d["snap"] = SnapSpec(**d.get("snap", {}))
        d["layers"] = LayerSpec(**d.get("layers", {}))
        d["quality"] = QualitySpec(**d.get("quality", {}))
        d["distance_levels"] = [DistanceLevel(**x) for x in d.get("distance_levels", [])]
        d["regions"] = [
            RefinementRegion(
                name=r["name"], shape=r["shape"], mode=r["mode"],
                levels=[DistanceLevel(**lv) for lv in r.get("levels", [])],
                min=r.get("min"), max=r.get("max"),
                centre=r.get("centre"), radius=r.get("radius"),
                why=r.get("why", ""),
                gap_level=r.get('gap_level'),gap_mode=r.get('gap_mode','outside'),
            )
            for r in d.get("regions", [])
        ]
        return cls(**d)


# ======================================================================================
# locationInMesh
# ======================================================================================

def find_location_in_mesh(geometry_path: str | Path, bbox_min: np.ndarray, bbox_max: np.ndarray,
                          *, mode: str = "outside", n: int = 16) -> list[float]:
    """Choose ``locationInMesh``: the seed for the region snappyHexMesh *keeps*.

    Getting this wrong is a silent, expensive failure: snappy keeps whatever is
    reachable from this point after removing the closed surface, so a seed inside a
    hollow body (a duct, a shell, a void) meshes the wrong side and every later metric
    is meaningless.

    ``mode='outside'`` (default, external flow)
        Seed the *fluid*: a point outside the surface, in the mid-field shell around the
        body, closest to the body centre.  The exterior is always the region we want, and
        it is never empty, so this is robust for any input including tubes, shells and
        multi-shell geometries.

    ``mode='inside'``
        Seed the body interior (deepest interior point).  Only correct when the intent is
        to mesh *inside* a closed surface.

    Inside/outside is decided by the sign of the offset along the nearest surface
    normal: outside where ``dot(p - q, n_q) > 0`` for the nearest surface point ``q``
    with outward normal ``n_q``.  That needs no ray casting, so it stays cheap on
    million-triangle STLs.
    """
    from scipy.spatial import cKDTree

    import trimesh
    from .geometry import sample
    mesh=trimesh.load(geometry_path,force='mesh',process=True)
    pts,nrm,_=sample(mesh,min(60_000,max(len(mesh.faces),2000)))
    tree = cKDTree(pts)

    lo = np.asarray(bbox_min, dtype=float)
    hi = np.asarray(bbox_max, dtype=float)
    diag = float(np.linalg.norm(hi - lo))
    centre = 0.5 * (lo + hi)

    def signed_outside(q: np.ndarray) -> np.ndarray:
        d, idx = tree.query(q, k=1, workers=-1)
        q = np.atleast_2d(q)
        return np.einsum("ij,ij->i", q - pts[idx], nrm[idx]) > 0.0

    if mode == "inside":
        # densest interior candidate set on a coarse lattice
        grid = np.linspace(0.05, 0.95, max(n, 6))
        gx, gy, gz = np.meshgrid(*(grid,) * 3, indexing="ij")
        cand = np.column_stack([
            lo[0] + gx.ravel() * (hi[0] - lo[0]),
            lo[1] + gy.ravel() * (hi[1] - lo[1]),
            lo[2] + gz.ravel() * (hi[2] - lo[2]),
        ])
        ins = ~signed_outside(cand)
        cand = cand[ins]
        if len(cand) == 0:
            return [float(v) for v in centre]
        d, _ = tree.query(cand, k=1, workers=-1)
        return [float(v) for v in cand[int(np.argmax(d))]]

    # mode == 'outside': ring of candidates at half a diagonal from the body centre,
    # plus the bbox corners; pick the valid one closest to the centre.
    rng = np.random.default_rng(0)
    dirs = rng.standard_normal((512, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    ring = centre[None, :] + dirs * (0.5 * diag)
    corners = np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
                        [hi[0], hi[1], lo[2]], [lo[0], hi[1], lo[2]],
                        [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                        [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]])
    cand = np.vstack([ring, corners, centre[None, :]])
    out = signed_outside(cand)
    if not out.any():
        # orientation is inconsistent; fall back to the farthest bbox corner, which is
        # outside for any sane body and is at worst a diagnosable failure
        return [float(v) for v in corners[6]]
    cand = cand[out]
    d = np.linalg.norm(cand - centre, axis=1)
    return [float(v) for v in cand[int(np.argmin(d))]]


# ======================================================================================
# dict writers
# ======================================================================================

#: Upper bound on the background grid.  blockMesh builds this on every round, so it must
#: stay a small fraction of the total budget; refinement, not the background, is what
#: puts cells where they are needed.
MAX_BACKGROUND_CELLS = 1_500_000
FOAM_HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2412                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //
"""


def _fmt(v: float) -> str:
    return f"{v:.10g}"


def _vec(v) -> str:
    return "(" + " ".join(_fmt(float(x)) for x in v) + ")"


def write_block_mesh_dict(spec: MeshSpec, bbox_min: np.ndarray, bbox_max: np.ndarray,
                          out: Path) -> dict[str, Any]:
    """Axis-aligned background box, sized from the body bbox and the domain spec."""
    d = spec.domain
    diag = float(np.linalg.norm(bbox_max - bbox_min))
    if diag <= 0:
        raise ValueError("degenerate bounding box")

    if d.mode == "box":
        # Agent contract: +X flow, +Z vertical. Side padding belongs to Y.
        pad_lo = np.array([d.padding_upstream, d.padding_side, d.padding_down]) * diag
        pad_hi = np.array([d.padding_downstream, d.padding_side, d.padding_up]) * diag
    else:
        pad_lo = np.array([d.padding_upstream, d.padding_side, d.padding_side]) * diag
        pad_hi = np.array([d.padding_downstream, d.padding_side, d.padding_side]) * diag
        # roll so that the flow axis is 'axis'
        pad_lo = np.roll(pad_lo, d.axis)
        pad_hi = np.roll(pad_hi, d.axis)

    lo = np.asarray(bbox_min, dtype=float) - pad_lo
    hi = np.asarray(bbox_max, dtype=float) + pad_hi

    extent = hi - lo
    longest_body = float(np.max(bbox_max - bbox_min))
    base = longest_body / max(d.base_cells, 1)
    counts = np.maximum(np.round(extent / base).astype(int), 1)

    # guard: the background mesh must stay a sane size
    n_cells = int(np.prod(counts))
    if n_cells > MAX_BACKGROUND_CELLS:
        # Coarsen rather than proceed.  blockMesh rebuilds this grid on every round, so
        # an oversized background silently dominates the whole budget and can look like
        # a hang.  This guard exists because a domain a few diagonals across with a fine
        # base cell once produced a 14-million-cell background grid.
        base *= (n_cells / MAX_BACKGROUND_CELLS) ** (1.0 / 3.0)
        counts = np.maximum(np.round(extent / base).astype(int), 1)
        n_cells = int(np.prod(counts))
    # ------------------------------------------------------------------------------
    # Vertex ordering and boundary faces.
    #
    # The block is emitted with the canonical OpenFOAM hex ordering, which is NOT the
    # naive "walk the bottom face then the top face" order.  With this numbering the
    # x direction is 0->1, y is 0->3 and z is 0->4, and the six outward faces are
    #   xMin (0 4 7 3)   xMax (2 6 5 1)
    #   yMin (0 1 5 4)   yMax (3 7 6 2)
    #   zMin (0 3 2 1)   zMax (4 5 6 7)
    # each verified by computing the face normal (b-a)x(c-a) and checking that it points
    # away from the block centre.
    #
    # Getting this wrong is not cosmetic.  With a mismatched ordering blockMesh reports
    # "trying to specify a boundary face ... which is either an internal face or already
    # belongs to some other patch" and then hangs without writing anything, which looks
    # exactly like a filesystem or subprocess fault.  That misdiagnosis cost hours.
    # ------------------------------------------------------------------------------
    vertices = [
        (lo[0], lo[1], lo[2]),   # 0
        (hi[0], lo[1], lo[2]),   # 1  +x
        (hi[0], hi[1], lo[2]),   # 2  +x +y
        (lo[0], hi[1], lo[2]),   # 3  +y
        (lo[0], lo[1], hi[2]),   # 4  +z
        (hi[0], lo[1], hi[2]),   # 5  +x +z
        (hi[0], hi[1], hi[2]),   # 6  +x +y +z
        (lo[0], hi[1], hi[2]),   # 7  +y +z
    ]
    face_x_min = (0, 4, 7, 3)
    face_x_max = (2, 6, 5, 1)
    face_y_min = (0, 1, 5, 4)
    face_y_max = (3, 7, 6, 2)
    face_z_min = (0, 3, 2, 1)
    face_z_max = (4, 5, 6, 7)

    if d.mode == "box":
        patches = [
            ("minX", "patch", [face_x_min]),
            ("maxX", "patch", [face_x_max]),
            ("minY", "patch", [face_y_min]),
            ("maxY", "patch", [face_y_max]),
            ("minZ", "patch", [face_z_min]),
            ("maxZ", "patch", [face_z_max]),
        ]
    else:
        ax = d.axis
        others = [a for a in (0, 1, 2) if a != ax]
        lo_by_axis = {0: face_x_min, 1: face_y_min, 2: face_z_min}
        hi_by_axis = {0: face_x_max, 1: face_y_max, 2: face_z_max}
        patches = [
            ("outlet", "patch", [hi_by_axis[ax]]),
            ("inlet", "patch", [lo_by_axis[ax]]),
        ]
        for a in others:
            patches.append((f"side{a}", "patch", [lo_by_axis[a], hi_by_axis[a]]))

    grading = d.grading
    body = FOAM_HEADER.format(obj="blockMeshDict")
    body += f"\nscale   1;\n\nvertices\n(\n"
    for v in vertices:
        body += f"    {_vec(v)}\n"
    body += ");\n\nblocks\n(\n"
    body += (f"    hex (0 1 2 3 4 5 6 7) ({counts[0]} {counts[1]} {counts[2]}) "
             f"simpleGrading ({_fmt(grading)} {_fmt(grading)} {_fmt(grading)})\n")
    body += ");\n\nedges\n(\n);\n\nboundary\n(\n"
    for name, typ, fs in patches:
        body += f"    {name}\n    {{\n        type {typ};\n        faces\n        (\n"
        for f in fs:
            body += "            (" + " ".join(str(i) for i in f) + ")\n"
        body += "        );\n    }\n"
    body += ");\n\nmergePatchPairs\n(\n);\n\n"
    body += "// ************************************************************************* //\n"
    out.write_text(body)

    return {
        "domain_min": [float(x) for x in lo],
        "domain_max": [float(x) for x in hi],
        "base_cell_size": base,
        "counts": [int(c) for c in counts],
        "background_cells": n_cells,
        "bbox_diagonal": diag,
    }


def write_surface_feature_extract_dict(spec: MeshSpec, stl_name: str, out: Path) -> None:
    f = spec.features
    body = FOAM_HEADER.format(obj="surfaceFeatureExtractDict")
    body += f"""
{stl_name}
{{
    extractionMethod    extractFromSurface;
    includedAngle       {_fmt(f.included_angle)};
    subsetFeatures
    {{
        nonManifoldEdges    {'yes' if f.non_manifold_edges else 'no'};
        openEdges           {'yes' if f.open_edges else 'no'};
    }}
    writeObj            yes;
}}

// ************************************************************************* //
"""
    out.write_text(body)


def render_snappy_hex_mesh_dict(spec: MeshSpec, stl_name: str, surface_name: str,
                                location_in_mesh, feature_file: str | None) -> str:
    q = spec.quality
    s = spec.snap
    l = spec.layers
    f = spec.features

    body = FOAM_HEADER.format(obj="snappyHexMeshDict")
    body += f"""
castellatedMesh true;
snap            true;
addLayers       {'true' if l.enabled else 'false'};

geometry
{{
    {stl_name}
    {{
        type triSurfaceMesh;
        name {surface_name};
    }}
"""
    if spec.distance_levels:
        # Deliberately NO second geometry entry here.
        #
        # Declaring the same STL twice (e.g. as "body" and "body_shells") looks harmless
        # but is silently catastrophic: OpenFOAM's searchableSurfaces loads each file
        # once, so the second name ends up with zero faces and the mesher reports
        #     Not all entries in refinementSurfaces dictionary were used
        #     ... not used : 1(body)
        #     Marked for refinement due to surface intersection : 0 cells
        # It then meshes the *empty box* -- no body patch at all -- while checkMesh still
        # reports zero failures.  A green verdict on a mesh that does not contain the
        # geometry is the worst failure mode this harness can have, so distance
        # refinement is instead expressed through refinementRegions on the single
        # surface name (snappyHexMesh supports 'distance' mode for searchable surfaces).
        pass
    for r in spec.regions:
        if r.shape == "box":
            body += f"""
    {r.name}
    {{
        type searchableBox;
        min  {_vec(r.min)};
        max  {_vec(r.max)};
    }}
"""
        else:
            body += f"""
    {r.name}
    {{
        type searchableSphere;
        origin {_vec(r.centre)};
        radius {_fmt(r.radius)};
    }}
"""
    body += "}\n\n\ncastellatedMeshControls\n{\n"
    body += f"""
    maxLocalCells {spec.max_local_cells};
    maxGlobalCells {spec.max_global_cells};
    minRefinementCells {spec.min_refinement_cells};
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels {spec.n_cells_between_levels};

    resolveFeatureAngle {_fmt(spec.resolve_feature_angle)};

    // Explicit feature edge refinement
    features
    (
"""
    if f.enabled and feature_file:
        body += f"""        {{
            file "{feature_file}";
            level {f.level};
        }}
"""
    body += "    );\n\n    // Surface based refinement\n    refinementSurfaces\n    {\n"
    body += f"""        {surface_name}
        {{
            level ({spec.surface.level_min} {spec.surface.level_max});
            patchInfo
            {{
                type {spec.surface.patch_type};
                inGroups ({spec.surface.patch_group});
            }}
        }}
    }}

    // Region-wise refinement
    refinementRegions
    {{
"""
    for r in spec.regions:
        body += f"""        {r.name}
        {{
            mode {r.mode};
            levels
            (
"""
        for lv in r.levels:
            body += f"                ({_fmt(lv.distance)} {lv.level})\n"
        body += "            );\n"
        if r.gap_level is not None:
            body += f"            gapLevel ({' '.join(str(v) for v in r.gap_level)});\n            gapMode {r.gap_mode};\n"
        body += "        }\n"

    if spec.distance_levels:
        # Shell distances are physical lengths in the canonical coordinate frame.
        body += f"""        {surface_name}
        {{
            mode distance;
            levels
            (
"""
        for lv in spec.distance_levels:
            body += f"                ({_fmt(lv.distance)} {lv.level})\n"
        body += "            );\n        }\n"

    body += "    }\n\n"
    body += f"    locationInMesh {_vec(location_in_mesh)};\n"
    body += f"    allowFreeStandingZoneFaces {'true' if spec.allow_free_standing_zone_faces else 'false'};\n"
    body += "}\n\n\nsnapControls\n{\n"
    body += f"""    nSmoothPatch {s.n_smooth_patch};
    tolerance {_fmt(s.tolerance)};
    nSolveIter {s.n_solve_iter};
    nRelaxIter {s.n_relax_iter};
    nFeatureSnapIter {s.n_feature_snap_iter};
    implicitFeatureSnap {'true' if s.implicit_feature_snap else 'false'};
    explicitFeatureSnap {'true' if s.explicit_feature_snap else 'false'};
    multiRegionFeatureSnap false;
    nFaceSplitInterval {s.n_face_split_interval};
    avoidDiagonal {'true' if s.avoid_diagonal else 'false'};
    concaveAngle {_fmt(s.concave_angle)};
    minAreaRatio {_fmt(s.min_area_ratio)};
}}

"""

    body += "\naddLayersControls\n{\n"
    body += f"    relativeSizes {'false' if l.first_layer_thickness > 0 else 'true'};\n\n    layers\n    {{\n"
    if l.enabled:
        body += f"""        "({surface_name}).*"
        {{
            nSurfaceLayers {l.n_surface_layers};
        }}
"""
    else:
        body += f"""        "({surface_name}).*"
        {{
            nSurfaceLayers 0;
        }}
"""
    body += "    }\n\n"
    body += f"""    expansionRatio {_fmt(l.expansion_ratio)};
    {'firstLayerThickness' if l.first_layer_thickness > 0 else 'finalLayerThickness'} {_fmt(l.first_layer_thickness if l.first_layer_thickness > 0 else l.final_layer_thickness)};
    minThickness {_fmt(l.min_thickness)};
    nGrow {l.n_grow};
    featureAngle {_fmt(l.feature_angle)};
    mergePatchFacesAngle {_fmt(l.merge_patch_faces_angle)};
    layerTerminationAngle {_fmt(l.layer_termination_angle if l.layer_termination_angle is not None else .5*l.feature_angle)};
    detectExtrusionIsland {'true' if l.detect_extrusion_island else 'false'};
    slipFeatureAngle {_fmt(l.slip_feature_angle)};
    nRelaxIter {l.n_relax_iter};
    nSmoothSurfaceNormals {l.n_smooth_surface_normals};
    nSmoothNormals {l.n_smooth_normals};
    nSmoothThickness {l.n_smooth_thickness};
    maxFaceThicknessRatio {_fmt(l.max_face_thickness_ratio)};
    maxThicknessToMedialRatio {_fmt(l.max_thickness_to_medial_ratio)};
    minMedialAxisAngle {_fmt(l.min_medial_axis_angle)};
    nBufferCellsNoExtrude {l.n_buffer_cells_no_extrude};
    nLayerIter {l.n_layer_iter};
    nOuterIter {l.n_outer_iter};
    meshShrinker {l.mesh_shrinker};
    additionalReporting true;
}}

meshQualityControls
{{
    #include "meshQualityDict"

    maxNonOrtho {_fmt(q.max_non_ortho)};
    maxBoundarySkewness {_fmt(q.max_boundary_skewness)};
    maxInternalSkewness {_fmt(q.max_internal_skewness)};
    maxConcave {_fmt(q.max_concave)};
    minVol {_fmt(q.min_vol)};
    minTetQuality {_fmt(q.min_tet_quality)};
    minArea {_fmt(q.min_area)};
    minTwist {_fmt(q.min_twist)};
    minDeterminant {_fmt(q.min_determinant)};
    minFaceWeight {_fmt(q.min_face_weight)};
    minVolRatio {_fmt(q.min_vol_ratio)};
    minTriangleTwist {_fmt(q.min_triangle_twist)};
    nSmoothScale {q.n_smooth_scale};
    errorReduction {_fmt(q.error_reduction)};
}}

debugFlags ();

writeFlags
(
    scalarLevels
    layerSets
    layerFields
);

mergeTolerance {_fmt(spec.merge_tolerance)};

// ************************************************************************* //
"""
    if l.mesh_shrinker == 'displacementMotionSolver':
        body=body.replace('    meshShrinker displacementMotionSolver;', '''    meshShrinker displacementMotionSolver;
    solver displacementLaplacian;
    displacementLaplacianCoeffs
    {
        diffusivity quadratic inverseDistance 1(body);
    }''')
    return body


def write_mesh_quality_dict(spec: MeshSpec, out: Path) -> None:
    """Only *deviations* from the OpenFOAM defaults are written here.

    The defaults themselves are pulled from ``caseDicts/meshQualityDict`` inside the
    installation, which guarantees they match the version actually running.
    """
    q = spec.quality
    body = FOAM_HEADER.format(obj="meshQualityDict")
    body += """
#includeEtc "caseDicts/meshQualityDict"

// Overrides (kept minimal on purpose: the version default is the reference)
"""
    defaults = {
        "maxNonOrtho": 65.0, "maxBoundarySkewness": 20.0, "maxInternalSkewness": 4.0,
        "maxConcave": 80.0, "minVol": 1e-13, "minTetQuality": 1e-15,
        "minTwist": 0.02, "minDeterminant": 0.001, "minFaceWeight": 0.02,
        "minVolRatio": 0.01,
    }
    for name, val in defaults.items():
        got = getattr(q, _snake(name))
        if abs(float(got) - val) > 1e-15 * max(1.0, abs(val)):
            body += f"{name} {_fmt(float(got))};\n"
    body += "\n// ************************************************************************* //\n"
    out.write_text(body)


def _snake(camel: str) -> str:
    out = []
    for i, ch in enumerate(camel):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def write_control_dict(out: Path, application: str = "snappyHexMesh",
                       write_format: str = "binary") -> None:
    body = FOAM_HEADER.format(obj="controlDict")
    body += f"""
application     {application};

startFrom       startTime;
startTime       0;

stopAt          endTime;
endTime         1;

deltaT          1;

writeControl    timeStep;
writeInterval   1;

purgeWrite      0;

writeFormat     {write_format};
writePrecision  17;

writeCompression off;

timeFormat      general;
timePrecision   6;

runTimeModifiable true;

// ************************************************************************* //
"""
    out.write_text(body)


# ======================================================================================
# case assembly
# ======================================================================================

@dataclass
class CaseLayout:
    root: Path
    stl_name: str
    surface_name: str
    system_dir: Path
    tri_surface_dir: Path

    @property
    def block_mesh_dict(self) -> Path:
        return self.system_dir / "blockMeshDict"

    @property
    def snappy_dict(self) -> Path:
        return self.system_dir / "snappyHexMeshDict"


def build_case(spec: MeshSpec, geometry: str | Path, case_root: str | Path, *,
               of_project_dir: str | Path, template_case: str | Path | None = None,
               bbox_min: np.ndarray | None = None,
               bbox_max: np.ndarray | None = None,
               surface_name: str = "body") -> tuple[CaseLayout, dict[str, Any]]:
    """Materialise a complete, runnable OpenFOAM case directory.

    ``template_case`` supplies the "boring" dictionaries (fvSchemes, fvSolution) so they
    always match the installed OpenFOAM version instead of being hard-coded here.
    """
    spec.validate()
    geometry = Path(geometry)
    case_root = Path(case_root)
    system_dir = case_root / "system"
    tri_surface_dir = case_root / "constant" / "triSurface"
    for p in (system_dir, tri_surface_dir):
        p.mkdir(parents=True, exist_ok=True)

    stl_name = geometry.name
    if geometry.resolve() != (tri_surface_dir / stl_name).resolve():
        shutil.copy2(geometry, tri_surface_dir / stl_name)

    # --- boring dictionaries, from the installed OpenFOAM ---
    of_project_dir = Path(of_project_dir)
    tmpl = Path(template_case) if template_case else (
        of_project_dir / "tutorials" / "incompressible" / "simpleFoam" / "motorBike" / "system")
    for name in ("fvSchemes", "fvSolution"):
        src = tmpl / name
        if src.is_file():
            shutil.copy2(src, system_dir / name)
        else:
            raise FileNotFoundError(f"template dict not found: {src}")
    if spec.layers.mesh_shrinker == 'displacementMotionSolver':
        # Meshing-only motion equations; physical solve creates its own dictionaries.
        (system_dir/'fvSolution').write_text(FOAM_HEADER.format(obj='fvSolution')+'''
solvers { "cellDisplacement.*" { solver GAMG; tolerance 1e-8; relTol 0;
    smoother GaussSeidel; } }
''')
        (system_dir/'fvSchemes').write_text(FOAM_HEADER.format(obj='fvSchemes')+'''
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
''')
    write_control_dict(system_dir / "controlDict", write_format=spec.write_format)
    write_mesh_quality_dict(spec, system_dir / "meshQualityDict")

    # --- geometry-derived fields ---
    if bbox_min is None or bbox_max is None:
        from .geometry import _read_tri_surface
        v, _ = _read_tri_surface(geometry)
        bbox_min = v.min(axis=0)
        bbox_max = v.max(axis=0)
    bbox_min = np.asarray(bbox_min, dtype=float)
    bbox_max = np.asarray(bbox_max, dtype=float)

    info = write_block_mesh_dict(spec, bbox_min, bbox_max, system_dir / "blockMeshDict")

    # --- features ---
    feature_file = None
    if spec.features.enabled:
        write_surface_feature_extract_dict(spec, stl_name, system_dir / "surfaceFeatureExtractDict")
        feature_file = f"{geometry.stem}.eMesh"

    # --- locationInMesh ---
    loc = spec.location_in_mesh
    if loc is None:
        # An exterior seed upstream of the source bbox cannot select a sealed
        # cavity, independent of local normals or semantic part labels.
        domain_lo=np.asarray(info['domain_min']);domain_hi=np.asarray(info['domain_max'])
        cell=(domain_hi-domain_lo)/np.asarray(info['counts'])
        centre=(bbox_min+bbox_max)/2
        loc=domain_lo+(np.floor((centre-domain_lo)/cell)+.5)*cell
        loc[0]=domain_lo[0]+.413*(bbox_min[0]-domain_lo[0])
        loc=loc.tolist()
    info["location_in_mesh"] = [float(x) for x in loc]

    # --- snappy dict ---
    (system_dir / "snappyHexMeshDict").write_text(
        render_snappy_hex_mesh_dict(spec, stl_name, surface_name, loc, feature_file))

    layout = CaseLayout(root=case_root, stl_name=stl_name, surface_name=surface_name,
                        system_dir=system_dir, tri_surface_dir=tri_surface_dir)
    info["case_root"] = str(case_root)
    info["finest_cell_size"] = info["base_cell_size"] / (2 ** spec.surface.level_max)
    return layout, info
