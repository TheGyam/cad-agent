"""The agent loop with a scripted model in place of the API."""

import json
from types import SimpleNamespace as NS

from agent import checker, loop
from agent.memory import Memory

SPEC = next(s for s in checker.load_specs() if s["id"] == "plate_02")
USAGE = NS(prompt_tokens=100, completion_tokens=50, total_tokens=150)


class ScriptedModel:
    """Answers each tool request with the next script, and lesson requests with `lesson`."""

    def __init__(self, replies, lesson="Select the face again before adding each new feature."):
        self.replies, self.lesson, self.requests = list(replies), lesson, []

    def chat(self, messages, tools=None):
        self.requests.append(messages)
        if not tools:
            return NS(content=self.lesson, tool_calls=None), USAGE
        reply = self.replies.pop(0)
        if reply is None:  # a reply with no tool call
            return NS(content="Here is my plan.", tool_calls=None), USAGE
        call = NS(id=f"call_{len(self.requests)}",
                  function=NS(name="run_and_check", arguments=json.dumps({"code": reply})))
        return NS(content="", tool_calls=[call]), USAGE


def test_fixes_the_part_from_feedback_and_learns_a_lesson(tmp_path):
    wrong = SPEC["reference"].replace("hole(20)", "hole(18)")
    model = ScriptedModel([wrong, SPEC["reference"]])
    memory = Memory(tmp_path / "lessons.json")
    logged = []

    task = loop.solve(SPEC, model, memory=memory, log=logged.append)

    assert task["passed"] and task["attempts"] == 2
    assert [a["categories"] for a in logged] == [["hole_diameter", "volume"], []]
    retry = model.requests[1]
    assert len(retry) == 4  # system, spec, the last attempt and its result: no older history
    assert retry[-1]["role"] == "tool" and "hole_diameter" in retry[-1]["content"]
    assert task["lesson"]["kept"]
    assert memory.relevant("plate") == [model.lesson]
    assert Memory(tmp_path / "lessons.json").relevant("plate") == [model.lesson]  # saved to disk


def test_lessons_go_into_the_prompt(tmp_path):
    memory = Memory(tmp_path / "lessons.json")
    memory.add("Always check which face a workplane sits on.", SPEC)
    model = ScriptedModel([SPEC["reference"]])
    task = loop.solve(SPEC, model, memory=memory)
    assert task["passed"] and task["lessons_in_prompt"] == 1 and "lesson" not in task
    assert "Always check which face" in model.requests[0][1]["content"]


def test_a_rejected_tool_call_counts_as_an_attempt():
    import openai

    class RejectsFirstCall(ScriptedModel):
        def chat(self, messages, tools=None):
            if tools and not self.requests:
                self.requests.append(messages)
                response = NS(status_code=400, headers={}, request=None)
                raise openai.BadRequestError("Failed to parse tool call arguments as JSON", response=response, body=None)
            return super().chat(messages, tools)

    task = loop.solve(SPEC, RejectsFirstCall([SPEC["reference"]]))
    assert task["passed"] and task["attempts"] == 2


def test_stops_after_the_last_attempt(tmp_path):
    model = ScriptedModel(["result = (", None, "result = ("])
    logged = []
    task = loop.solve(SPEC, model, max_attempts=3, log=logged.append)
    assert not task["passed"] and task["attempts"] == 3
    assert [a["categories"] for a in logged] == [["syntax_error"], ["no_code"], ["syntax_error"]]


def test_every_guide_example_builds_what_it_claims():
    from agent.runner import build_trusted

    holes = {}
    volumes = {}
    for name, code in {**loop.GUIDE_EXAMPLES, **loop.ROUND_EXAMPLES, **loop.PLANE_EXAMPLES}.items():
        shape = build_trusted(code)
        assert len(shape.Solids()) == 1 and shape.isValid(), name
        volumes[name] = round(shape.Volume())
        holes[name] = sorted((round(h["d"], 2), h["axis"], tuple(round(v, 2) for v in h["at"]), round(h["depth"], 2))
                             for h in checker.find_holes(shape))
    assert holes["plate with holes"] == [(5.0, "z", (10.0, 10.0), 6.0), (5.0, "z", (70.0, 10.0), 6.0)]
    assert {h[2] for h in holes["bolt circle"]} == {(55.0, 25.0), (40.0, 40.0), (25.0, 25.0), (40.0, 10.0)}
    assert holes["hole along Y"] == [(6.0, "y", (40.0, 15.0), 50.0)]
    assert holes["round flange"] == [(6.0, "z", (10.0, 40.0), 10.0), (6.0, "z", (40.0, 10.0), 10.0),
                                     (6.0, "z", (40.0, 70.0), 10.0), (6.0, "z", (70.0, 40.0), 10.0),
                                     (20.0, "z", (40.0, 40.0), 10.0)]
    assert all(name in loop.GUIDE for name in loop.GUIDE_EXAMPLES)
    assert all(name in loop.GUIDE_V2 for name in {**loop.GUIDE_EXAMPLES, **loop.ROUND_EXAMPLES})
    assert "round flange" not in loop.GUIDE and loop.ROUND_NOTE in loop.GUIDE_V2
    # the rib spans Y = 17 to 23: 12,000 + 8,000 - 1,000 overlap + a 30 x 30 / 2 x 6 rib
    assert volumes["rib drawn on the XZ plane"] == 21700
    assert holes["holes in a floor"] == [(4.0, "z", (10.0, 10.0), 3.0), (4.0, "z", (50.0, 30.0), 3.0)]
    assert all(name in loop.GUIDE_V3 for name in {**loop.GUIDE_EXAMPLES, **loop.ROUND_EXAMPLES, **loop.PLANE_EXAMPLES})
    assert loop.ROUND_NOTE in loop.GUIDE_V3 and loop.PLANE_NOTE in loop.GUIDE_V3
    assert "XZ plane" not in loop.GUIDE_V2


def test_guided_mode_adds_the_guide_hints_and_history():
    no_hole = SPEC["reference"].replace('.faces(">Z").workplane().hole(20)', "")
    model = ScriptedModel([no_hole, no_hole, SPEC["reference"]])

    task = loop.solve(SPEC, model, guide=loop.GUIDE)

    assert task["passed"] and task["attempts"] == 3
    assert loop.GUIDE in model.requests[0][0]["content"]
    second, third = model.requests[1][-1]["content"], model.requests[2][-1]["content"]
    assert "hint: the part has no round holes" in second and "Earlier attempts" not in second
    # the history lists earlier attempts; the latest one's failures are the feedback above it
    assert "- attempt 1: hole_count, volume" in third and "- attempt 2" not in third


def test_unguided_feedback_has_no_hints():
    model = ScriptedModel([SPEC["reference"].replace('.faces(">Z").workplane().hole(20)', ""), SPEC["reference"]])
    loop.solve(SPEC, model)
    assert loop.GUIDE not in model.requests[0][0]["content"]
    assert "hint:" not in model.requests[1][-1]["content"]


def test_separate_solids_are_listed_in_the_hint():
    import cadquery as cq

    two = cq.Compound.makeCompound([cq.Solid.makeBox(10, 10, 10), cq.Solid.makeBox(5, 5, 5, cq.Vector(20, 0, 0))])
    [v] = checker.check(SPEC, two, checker.reference_shape(SPEC))
    assert v["category"] == "invalid_solid"
    assert "1,000 mm3 from (0.0, 0.0, 0.0) to (10.0, 10.0, 10.0)" in v["hint"]
    assert "125 mm3 from (20.0, 0.0, 0.0)" in v["hint"]
