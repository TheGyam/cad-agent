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


def test_stops_after_the_last_attempt(tmp_path):
    model = ScriptedModel(["result = (", None, "result = ("])
    logged = []
    task = loop.solve(SPEC, model, max_attempts=3, log=logged.append)
    assert not task["passed"] and task["attempts"] == 3
    assert [a["categories"] for a in logged] == [["syntax_error"], ["no_code"], ["syntax_error"]]
