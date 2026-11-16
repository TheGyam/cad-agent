from agent.memory import Memory

SPEC = {"id": "plate_01", "family": "plate", "text": "Plate 80 mm by 50 mm, four 5 mm holes 10 mm from the edges."}


def test_keeps_general_lessons_and_refuses_the_rest(tmp_path):
    m = Memory(tmp_path / "lessons.json")
    assert m.add("Call .faces('>Z').workplane() again before each new hole pattern.", SPEC) is None
    assert "numbers" in m.add("Put the holes 10 mm from the edges.", SPEC)
    assert "nearly the same" in m.add("Call .faces('>Z').workplane() again before every new hole pattern.", SPEC)
    assert m.add("", SPEC) is not None
    assert "about the tool" in m.add("Always include a `run_and_check` call with the `code` argument.", SPEC)
    assert len(m.lessons) == 1


def test_no_lesson_from_rejected_tool_calls_alone(tmp_path):
    class NeverCalled:
        def chat(self, *a, **k):
            raise AssertionError("no lesson should be asked for")

    rejected = {"categories": ["no_code"], "passed": False, "attempt": 1, "violations": []}
    passed = {"categories": [], "passed": True, "attempt": 2, "violations": []}
    assert Memory(tmp_path / "l.json").learn(NeverCalled(), SPEC, [rejected, passed]) is None


def test_relevant_prefers_the_same_family_then_the_newest(tmp_path):
    m = Memory(tmp_path / "lessons.json", limit=3)
    lessons = [
        ("plate", "Chamfer outer edges before drilling holes."),
        ("flange", "Use polarArray for bolt circles."),
        ("plate", "Re-select the top face after every cut."),
        ("bracket", "Union both legs before cutting holes."),
        ("flange", "Cut the bore after adding the hub."),
    ]
    for family, text in lessons:
        assert m.add(text, {**SPEC, "family": family}) is None
    assert m.relevant("flange") == [
        "Cut the bore after adding the hub.",
        "Use polarArray for bolt circles.",
        "Union both legs before cutting holes.",
    ]


def test_v2_keeps_only_short_plain_lessons_that_name_a_call(tmp_path):
    m = Memory(tmp_path / "lessons.json", strict=True)
    assert m.limit == 3
    assert m.add("Always verify that every feature is applied before finishing the model.", SPEC) == \
        "names no CadQuery call"
    assert m.add("Re-select the face with .faces() after .hole(), because hole() returns to the old plane. " * 3,
                 SPEC) == "longer than 30 words"
    assert m.add("After .hole(), select the face again with \u201c.faces()\u201d \u2011 hole() resets the plane.",
                 SPEC) is None
    assert m.relevant("plate") == ['After .hole(), select the face again with ".faces()" - hole() resets the plane.']
    assert m.add("Use polarArray() for bolt circles \u2603 to space them evenly.", SPEC) == "not plain ASCII"
