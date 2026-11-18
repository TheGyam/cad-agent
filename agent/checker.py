"""Measure a part against its spec and list every way it is wrong.

The checker is the ground truth of the benchmark, so each check is simple to
reason about and is tested on hand-written correct and broken parts
(tests/test_specs.py) before any model output is judged.

All positions are measured from the minimum corner of the part's bounding box,
so a model may build the part anywhere, but its orientation must match the spec.
"""

import functools
import math
from pathlib import Path

import cadquery as cq
import yaml
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepGProp import BRepGProp_Face
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN

BBOX_TOL = 0.1  # mm
VOLUME_TOL = 0.01  # fraction of the expected volume
HOLE_POS_TOL = 0.1  # mm
HOLE_DIA_TOL = 0.05  # mm
HOLE_DEPTH_TOL = 0.1  # mm
THICKNESS_TOL = 0.05  # mm
SHAPE_TOL = 0.001  # fraction of the reference volume that may differ from it (booleans are exact)

# Every failure falls in one of these. The loop reports no_code, the runner the
# next three, the checker the rest.
CATEGORIES = (
    "no_code", "syntax_error", "runtime_error", "timeout", "invalid_solid", "wrong_dimension",
    "volume", "hole_count", "hole_diameter", "hole_position", "hole_depth", "wrong_face",
    "wall_thickness", "shape_mismatch",
)
AXES = {"x": cq.Vector(1, 0, 0), "y": cq.Vector(0, 1, 0), "z": cq.Vector(0, 0, 1)}
SPEC_DIR = Path(__file__).resolve().parent.parent / "specs"


def load_specs(spec_dir: Path = SPEC_DIR) -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(Path(spec_dir).glob("*.yaml"))]


@functools.cache
def _build_reference(code: str) -> cq.Shape:
    from agent.runner import build_trusted

    return build_trusted(code)


def reference_shape(spec: dict) -> cq.Shape:
    """The spec's hand-written reference part, the shape a correct answer matches."""
    return _build_reference(spec["reference"])


def violation(category: str, message: str, hint: str | None = None) -> dict:
    """One failure. A hint is extra detail on where or why; condition D shows it to the model."""
    assert category in CATEGORIES, category
    return {"category": category, "message": message} | ({"hint": hint} if hint else {})


def check(spec: dict, shape: cq.Shape, reference: cq.Shape) -> list[dict]:
    """Return the violations of `shape` against `spec`; an empty list means it passes."""
    solids = shape.Solids()
    if len(solids) != 1:
        return [violation("invalid_solid", f"expected exactly one solid, found {len(solids)}", _solids_hint(solids))]
    solid = solids[0]
    if not solid.isValid() or solid.Volume() <= 0:
        return [violation("invalid_solid", "the solid is not valid (open, inside out or self-intersecting)")]

    solid, reference = to_origin(solid), to_origin(reference)
    c = spec["constraints"]
    out = check_bbox(solid, c["bbox"]) + check_volume(solid, reference.Volume())
    if "holes" in c:
        out += check_holes(solid, expand_holes(c["holes"]))
    if "thickness_min" in c:
        out += check_thickness(solid, c["thickness_min"])
    if not out:  # the catch-all, only when every named check has passed
        out = check_shape(solid, reference)
    return out


def to_origin(shape: cq.Shape) -> cq.Shape:
    bb = shape.BoundingBox()
    return shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))


def _fmt(values) -> str:
    return "(" + ", ".join(f"{v:.1f}" for v in values) + ")"


def _solids_hint(solids: list) -> str | None:
    if not solids:
        return None
    lo = cq.Compound.makeCompound(solids).BoundingBox()
    parts = []
    for s in sorted(solids, key=lambda s: -s.Volume())[:6]:
        bb = s.BoundingBox()
        parts.append(f"{s.Volume():,.0f} mm3 from {_fmt((bb.xmin - lo.xmin, bb.ymin - lo.ymin, bb.zmin - lo.zmin))} "
                     f"to {_fmt((bb.xmax - lo.xmin, bb.ymax - lo.ymin, bb.zmax - lo.zmin))}")
    return ("the separate solids are: " + "; ".join(parts) +
            ". Join features with .union(); a boss or rib must overlap the body to join it.")


# --- size --------------------------------------------------------------------

def check_bbox(solid: cq.Shape, expected) -> list[dict]:
    bb = solid.BoundingBox()
    size = (bb.xlen, bb.ylen, bb.zlen)
    if all(abs(a - b) <= BBOX_TOL for a, b in zip(size, expected)):
        return []
    got = " x ".join(f"{v:.1f}" for v in size)
    want = " x ".join(f"{v:g}" for v in expected)
    return [violation("wrong_dimension", f"bounding box is {got} mm (X x Y x Z), expected {want} mm")]


def check_volume(solid: cq.Shape, expected: float) -> list[dict]:
    vol = solid.Volume()
    if abs(vol - expected) <= VOLUME_TOL * expected:
        return []
    return [violation("volume", f"volume is {vol:,.0f} mm3, expected {expected:,.0f} mm3 (within 1%)")]


# --- holes -------------------------------------------------------------------

def expand_holes(groups: list[dict]) -> list[dict]:
    """Turn the spec's hole groups into one {d, depth, axis, at} per hole.

    `depth` is the length of the hole wall along its axis. A group lists positions with `at: [[a, b], ...]` or a bolt circle with
    `circle: {center: [a, b], r: R, n: N, start: degrees}`. (a, b) are the two
    coordinates across the axis in X, Y, Z order: (x, y) for a hole along Z.
    """
    holes = []
    for g in groups:
        points = g.get("at", [])
        if "circle" in g:
            c = g["circle"]
            points = [
                (c["center"][0] + c["r"] * math.cos(math.radians(c.get("start", 0) + 360 * i / c["n"])),
                 c["center"][1] + c["r"] * math.sin(math.radians(c.get("start", 0) + 360 * i / c["n"])))
                for i in range(c["n"])
            ]
        holes += [{"d": g["d"], "depth": g["depth"], "axis": g["axis"], "at": tuple(p)} for p in points]
    return holes


def _axis_name(direction: cq.Vector) -> str:
    for name, a in AXES.items():
        if abs(abs(direction.dot(a)) - 1) < 1e-6:
            return name
    return "other"


def _across(point: cq.Vector, axis: str) -> tuple:
    """The two coordinates of `point` across `axis`, in X, Y, Z order."""
    return tuple(v for name, v in zip("xyz", point.toTuple()) if name != axis)


def find_holes(solid: cq.Shape) -> list[dict]:
    """Every round hole: concave cylindrical faces that close a full circle.

    Faces on the same axis line with the same radius are one hole (OCC often
    splits a hole wall in two). Fillets and slot ends are concave too, but never
    close a full circle, so they are left out.
    """
    groups = []
    for face in solid.Faces():
        if face.geomType() != "CYLINDER":
            continue
        cyl = BRepAdaptor_Surface(face.wrapped).Cylinder()
        loc, d = cyl.Axis().Location(), cyl.Axis().Direction()
        p0, axis = cq.Vector(loc.X(), loc.Y(), loc.Z()), cq.Vector(d.X(), d.Y(), d.Z())
        umin, umax, vmin, vmax = face._uvBounds()

        point, normal = gp_Pnt(), gp_Vec()
        BRepGProp_Face(face.wrapped).Normal((umin + umax) / 2, (vmin + vmax) / 2, point, normal)
        p = cq.Vector(point.X(), point.Y(), point.Z())
        to_axis = p0 + axis * (p - p0).dot(axis) - p
        if cq.Vector(normal.X(), normal.Y(), normal.Z()).dot(to_axis) <= 0:
            continue  # convex: an outer surface or a boss, not a hole

        bb = face.BoundingBox()
        lo, hi = cq.Vector(bb.xmin, bb.ymin, bb.zmin), cq.Vector(bb.xmax, bb.ymax, bb.zmax)
        for g in groups:
            offset = p0 - g["p0"]
            same_line = abs(abs(axis.dot(g["axis"])) - 1) < 1e-6 and (offset - g["axis"] * offset.dot(g["axis"])).Length < 1e-3
            if same_line and abs(cyl.Radius() - g["r"]) < 1e-3:
                g["angle"] += umax - umin
                g["lo"], g["hi"] = _vmin(g["lo"], lo), _vmax(g["hi"], hi)
                break
        else:
            groups.append({"p0": p0, "axis": axis, "r": cyl.Radius(), "angle": umax - umin, "lo": lo, "hi": hi})

    holes = []
    for g in groups:
        if g["angle"] >= 2 * math.pi - 1e-3:
            name = _axis_name(g["axis"])
            if name == "other":
                holes.append({"d": 2 * g["r"], "axis": name, "at": (), "depth": math.nan})
                continue
            i = "xyz".index(name)
            depth = g["hi"].toTuple()[i] - g["lo"].toTuple()[i]
            holes.append({"d": 2 * g["r"], "axis": name, "at": _across(g["p0"], name), "depth": depth})
    return holes


def _vmin(a: cq.Vector, b: cq.Vector) -> cq.Vector:
    return cq.Vector(min(a.x, b.x), min(a.y, b.y), min(a.z, b.z))


def _vmax(a: cq.Vector, b: cq.Vector) -> cq.Vector:
    return cq.Vector(max(a.x, b.x), max(a.y, b.y), max(a.z, b.z))


def _near(a, b, tol=HOLE_POS_TOL) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _dist(a, b) -> float:
    return math.dist(a, b) if len(a) == len(b) else math.inf


def check_holes(solid: cq.Shape, expected: list[dict]) -> list[dict]:
    found = find_holes(solid)
    left = list(found)  # found holes not yet matched to an expected one
    missing, depth_errors = [], []
    for e in expected:
        match = next((f for f in left if f["axis"] == e["axis"] and _near(f["at"], e["at"])
                      and abs(f["d"] - e["d"]) <= HOLE_DIA_TOL), None)
        if match:
            left.remove(match)
            if abs(match["depth"] - e["depth"]) > HOLE_DEPTH_TOL:
                depth_errors.append(violation(
                    "hole_depth", f"the {e['d']:g} mm hole along {e['axis'].upper()} at {_fmt(e['at'])} is "
                                  f"{match['depth']:.1f} mm deep, expected {e['depth']:g} mm"))
        else:
            missing.append(e)

    out = depth_errors
    if len(found) != len(expected):
        out.append(violation("hole_count", f"found {len(found)} round holes, expected {len(expected)}"))
    for e in missing:
        want = f"a {e['d']:g} mm hole along {e['axis'].upper()} at {_fmt(e['at'])}"
        same_spot = [f for f in left if f["axis"] == e["axis"] and _near(f["at"], e["at"])]
        same_size = [f for f in left if f["axis"] == e["axis"] and abs(f["d"] - e["d"]) <= HOLE_DIA_TOL]
        sideways = [f for f in left if f["axis"] != e["axis"] and abs(f["d"] - e["d"]) <= HOLE_DIA_TOL]
        if same_spot:
            f = same_spot[0]
            out.append(violation("hole_diameter", f"expected {want}; the hole there is {f['d']:.2f} mm"))
        elif same_size:
            f = min(same_size, key=lambda f: _dist(f["at"], e["at"]))
            out.append(violation("hole_position", f"expected {want}; the nearest such hole is at {_fmt(f['at'])}"))
        elif sideways:
            f = sideways[0]
            out.append(violation("wrong_face", f"expected {want}; found one along {f['axis'].upper()} "
                                               f"instead, so it is on the wrong face"))
        else:
            out.append(violation("hole_count", f"expected {want}; there is none"))
            continue
        left.remove(f)
    for f in left:
        out.append(violation("hole_count", f"unexpected {f['d']:.2f} mm hole along {f['axis'].upper()} "
                                           f"at {_fmt(f['at'])}"))
    if out:
        listed = "; ".join(f"{f['d']:.2f} mm along {f['axis'].upper()} at {_fmt(f['at'])}, {f['depth']:.1f} mm deep"
                           for f in found[:12])
        out[0]["hint"] = f"round holes found in the part: {listed}" if found else "the part has no round holes"
        if any(v["category"] == "hole_position" for v in out) and all(
                f["axis"] != "other" for f in found):
            out[0]["hint"] += (". Holes a little off usually come from a workplane centred on the face; "
                               "build the part from the origin with centered=False and use .workplane(origin=(0, 0, 0)), "
                               "so spec positions are plain coordinates")
    return out


# --- wall thickness ----------------------------------------------------------

def min_thickness(solid: cq.Shape, samples: int = 5) -> tuple[float, cq.Vector | None]:
    """Smallest wall thickness, measured by rays shot into the material.

    From a grid of points on every flat face, a ray goes inward along the face
    normal; the distance to the next surface is the local thickness. Curved faces
    are skipped so hole walls and bosses do not count as walls.

    ponytail: a sampled estimate (samples x samples points per face); a wall thinner
    than the spec only between sample points is missed. Raise `samples` if that matters.
    """
    rays = IntCurvesFace_ShapeIntersector()
    rays.Load(solid.wrapped, 1e-6)
    best, where = math.inf, None
    for face in solid.Faces():
        if face.geomType() != "PLANE":
            continue
        umin, umax, vmin, vmax = face._uvBounds()
        props = BRepGProp_Face(face.wrapped)
        for i in range(samples):
            for j in range(samples):
                u = umin + (i + 0.5) / samples * (umax - umin)
                v = vmin + (j + 0.5) / samples * (vmax - vmin)
                if BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-6).State() != TopAbs_IN:
                    continue
                p, n = gp_Pnt(), gp_Vec()
                props.Normal(u, v, p, n)
                rays.Perform(gp_Lin(p, gp_Dir(-n.X(), -n.Y(), -n.Z())), 1e-4, 1e6)
                hits = [rays.WParameter(k) for k in range(1, rays.NbPnt() + 1)]
                hits = [w for w in hits if w > 1e-3]
                if hits and min(hits) < best:
                    best, where = min(hits), cq.Vector(p.X(), p.Y(), p.Z())
    return best, where


def check_thickness(solid: cq.Shape, minimum: float) -> list[dict]:
    t, where = min_thickness(solid)
    if t >= minimum - THICKNESS_TOL:
        return []
    return [violation("wall_thickness", f"a wall is only {t:.2f} mm thick near {_fmt(where.toTuple())}, "
                                        f"expected at least {minimum:g} mm")]


# --- whole shape -------------------------------------------------------------

def check_shape(solid: cq.Shape, reference: cq.Shape) -> list[dict]:
    """Compare against the reference part: the material that is extra or missing.

    Catches what the named checks cannot see, such as an enclosure open on the
    wrong side, which has the right size, volume and holes.
    """
    limit = SHAPE_TOL * reference.Volume()
    out = []
    for name, diff in (("extra", solid.cut(reference)), ("missing", reference.cut(solid))):
        vol = diff.Volume()
        if vol > limit:
            share = 100 * vol / reference.Volume()
            out.append(violation("shape_mismatch", f"the shape does not match the spec: {share:.1f}% of the "
                                                   f"volume is {name}, centred near {_fmt(diff.Center().toTuple())}"))
    return out
