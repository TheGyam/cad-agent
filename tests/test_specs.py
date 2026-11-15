"""The checker against hand-written parts: every reference passes, every broken copy fails.

The checker is the benchmark's ground truth, so this file is what makes the
results believable. Each spec carries a reference part and broken copies, each
made by one text replacement in the reference and tagged with the failure the
checker must report.
"""

from collections import Counter

import cadquery as cq
import pytest

from agent import checker
from agent.runner import build_trusted

SPECS = checker.load_specs()
BROKEN = [(s, b) for s in SPECS for b in s.get("broken", [])]


def test_benchmark_has_thirty_specs_in_four_families():
    assert len(SPECS) == 30
    assert len({s["id"] for s in SPECS}) == 30
    assert Counter(s["family"] for s in SPECS) == {"plate": 10, "bracket": 8, "flange": 6, "enclosure": 6}
    assert {s["difficulty"] for s in SPECS} == {"easy", "medium", "hard"}
    for s in SPECS:
        assert set(s) <= {"id", "family", "difficulty", "text", "constraints", "reference", "broken"}, s["id"]
        assert len(s["broken"]) >= 2, s["id"]


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s["id"])
def test_reference_passes(spec):
    ref = checker.reference_shape(spec)
    assert checker.check(spec, ref, ref) == []


@pytest.mark.parametrize("spec,broken", BROKEN, ids=lambda x: x["id"] if "id" in x else x["expect"])
def test_broken_part_is_caught(spec, broken):
    old, new = broken["replace"]
    assert spec["reference"].count(old) == 1, f"{old!r} must appear exactly once"
    shape = build_trusted(spec["reference"].replace(old, new))
    found = {v["category"] for v in checker.check(spec, shape, checker.reference_shape(spec))}
    assert broken["expect"] in found, found


def test_position_does_not_matter_but_orientation_does():
    spec = next(s for s in SPECS if s["id"] == "bracket_03")
    ref = checker.reference_shape(spec)
    moved = ref.translate(cq.Vector(13, -7, 22))
    assert checker.check(spec, moved, ref) == []
    turned = ref.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 180)
    assert checker.check(spec, turned, ref) != []


def test_two_solids_are_not_one_part():
    spec = SPECS[0]
    two = cq.Compound.makeCompound([cq.Solid.makeBox(1, 1, 1), cq.Solid.makeBox(1, 1, 1, cq.Vector(5, 0, 0))])
    assert [v["category"] for v in checker.check(spec, two, checker.reference_shape(spec))] == ["invalid_solid"]


def test_fillets_and_slot_ends_are_not_holes():
    part = cq.Workplane("XY").box(60, 40, 6).edges("|Z").fillet(5).faces(">Z").workplane().slot2D(30, 8).cutThruAll()
    assert checker.find_holes(part.val()) == []


def test_bolt_circle_expands_counterclockwise_from_start():
    holes = checker.expand_holes([{"d": 9, "depth": 1, "axis": "z", "circle": {"center": [50, 50], "r": 10, "n": 4, "start": 90}}])
    assert [tuple(round(v, 6) for v in h["at"]) for h in holes] == [(50, 60), (40, 50), (50, 40), (60, 50)]
