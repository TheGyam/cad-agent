from agent.memory import Memory

SPEC = {"id": "plate_01", "family": "plate", "text": "Plate 80 mm by 50 mm, four 5 mm holes 10 mm from the edges."}


def test_keeps_general_lessons_and_refuses_the_rest(tmp_path):
    m = Memory(tmp_path / "lessons.json")
    assert m.add("Call .faces('>Z').workplane() again before each new hole pattern.", SPEC) is None
    assert "numbers" in m.add("Put the holes 10 mm from the edges.", SPEC)
    assert "nearly the same" in m.add("Call .faces('>Z').workplane() again before every new hole pattern.", SPEC)
    assert m.add("", SPEC) is not None
    assert len(m.lessons) == 1


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
