"""The agent loop: generate, run, check, feed back, up to `max_attempts` times.

The model works through one tool, run_and_check. Each call is one attempt: the
code runs in the sandbox, the checker measures the part, and the violations go
back as the tool's result. To keep requests small on a free token budget, a retry
carries the spec, the lessons, and only the latest attempt and its result.
"""

import json
import tempfile
import time
from pathlib import Path

import cadquery as cq
import openai

from agent import checker, runner
from agent.checker import violation
from agent.llm import RUN_AND_CHECK

SYSTEM = """You are a mechanical design engineer who writes CadQuery 2.x Python code.
Build the part described by the user as one single solid.

Rules:
- Units are millimetres. X is length, Y is width, Z is up.
- Positions in the spec are measured from the part's minimum corner (its
  minimum X, Y and Z). You may build the part anywhere: only its shape and
  orientation are checked, not where it sits.
- Holes go all the way through unless the spec says they are blind.
- The script must `import cadquery as cq` and assign the finished part to a
  variable named `result`. Use only cadquery and the Python standard library;
  do not read or write files.
- Call run_and_check with the complete script. If it reports violations, fix
  all of them and call it again with the complete corrected script."""

RETRY = "Fix every violation and call run_and_check again with the complete script."

# Condition D adds this guide to the system prompt. It covers the API mistakes that
# made most of the benchmark's crashed runs. Every example runs in tests/test_loop.py,
# so a wrong example fails the tests instead of reaching the model.
GUIDE_EXAMPLES = {
    "plate with holes": """\
import cadquery as cq
result = (cq.Workplane("XY").box(80, 50, 6, centered=False)
          .faces(">Z").workplane(origin=(0, 0, 0))
          .pushPoints([(10, 10), (70, 10)]).hole(5))""",
    "bolt circle": """\
import cadquery as cq
result = (cq.Workplane("XY").box(80, 50, 6, centered=False)
          .faces(">Z").workplane(origin=(40, 25, 0))
          .polarArray(15, 0, 360, 4).hole(4))""",
    "hole along Y": """\
import cadquery as cq
body = cq.Workplane("XY").box(80, 50, 30, centered=False)
result = body.cut(cq.Solid.makeCylinder(3, 50, cq.Vector(40, 0, 15), cq.Vector(0, 1, 0)))""",
    "fillets, chamfers and a joined boss": """\
import cadquery as cq
body = cq.Workplane("XY").box(80, 50, 6, centered=False).edges("|Z").fillet(3)
body = body.faces(">Z").edges().chamfer(0.5)
boss = cq.Workplane("XY").box(10, 10, 10, centered=False).translate((20, 20, 5))
result = body.union(boss)""",
}

GUIDE = """CadQuery notes (checked against CadQuery 2.x):
- Build from the origin corner with centered=False, so the spec's positions are
  plain coordinates. On a face, .workplane(origin=(0, 0, 0)) keeps X and Y global.
- .hole(d) cuts through the whole part unless you pass depth=. After .hole(),
  select the face again (.faces(">Z").workplane(origin=(0, 0, 0))) before the next feature.
- For a hole along X or Y, cut an explicit cylinder:
  cq.Solid.makeCylinder(radius, length, base_point, direction). Side-face workplanes
  have rotated local axes.
- Selectors name directions only: ">Z" top, "<Z" bottom, "|Z" parallel to Z,
  "#Z" perpendicular to Z, combined with and/or/not, e.g. "|Z and >X". There is no
  "X==0". To pick by position use cq.selectors.BoxSelector((x0, y0, z0), (x1, y1, z1)).
- .fillet() and .chamfer() need a solid and selected edges: make the solid first,
  then .edges(...).fillet(r).
- Join every feature into the body with .union(); a boss or rib must overlap the
  body, or the part is several solids.
- Use Python's math module. cq.math, cq.cos and cq.Cylinder do not exist.
  .workplane() has no center= argument; move with .center(x, y) or .moveTo(x, y).

Examples:
""" + "\n\n".join(f"# {name}\n{code}" for name, code in GUIDE_EXAMPLES.items())

# Condition E is D with this round-part note and example added. Guide v1 built round
# flanges as square blocks, because all its examples were boxes. GUIDE stays as it was,
# so condition D's logged runs can still be reproduced.
ROUND_EXAMPLES = {
    "round flange": """\
import cadquery as cq
disc = cq.Workplane("XY").circle(40).extrude(10).translate((40, 40, 0))
result = (disc.faces(">Z").workplane(origin=(40, 40, 0)).hole(20)
          .faces(">Z").workplane(origin=(40, 40, 0)).polarArray(30, 0, 360, 4).hole(6))""",
}

ROUND_NOTE = """- Round parts (discs, round flanges, hubs) start from a circle, not a box:
  .circle(r).extrude(h). Positions are measured from the minimum corner, so a disc of
  radius r has its centre at (r, r): move it there with .translate((r, r, 0))."""

GUIDE_V2 = GUIDE.replace("\n\nExamples:\n", "\n" + ROUND_NOTE + "\n\nExamples:\n") + "".join(
    f"\n\n# {name}\n{code}" for name, code in ROUND_EXAMPLES.items())

# Condition F is E with two more traps that failed every guided run on the second
# held-out set: "XZ" extrudes towards -Y, and a bottom-face workplane mirrors Y.
PLANE_EXAMPLES = {
    "rib drawn on the XZ plane": """\
import cadquery as cq
body = (cq.Workplane("XY").box(60, 40, 5, centered=False)
        .union(cq.Workplane("XY").box(5, 40, 40, centered=False)))
rib = cq.Workplane("XZ", origin=(0, 23, 0)).polyline([(5, 5), (35, 5), (5, 35)]).close().extrude(6)
result = body.union(rib)""",
    "holes in a floor": """\
import cadquery as cq
tray = cq.Workplane("XY").box(60, 40, 20, centered=False).faces(">Z").shell(-3)
holes = cq.Workplane("XY").pushPoints([(10, 10), (50, 30)]).circle(2).extrude(3)
result = tray.cut(holes)""",
}

PLANE_NOTE = """- "XY" faces +Z and "YZ" faces +X, but "XZ" faces -Y: .extrude(t) on "XZ" grows
  towards -Y. For a profile in X and Z that spans Y = y0 to y1, use
  cq.Workplane("XZ", origin=(0, y1, 0)) and .extrude(y1 - y0).
- A workplane on a bottom face ("<Z") has its local Y pointing to -Y, so points come
  out mirrored. For holes in a floor or base, cut cylinders from an "XY" workplane:
  cq.Workplane("XY").pushPoints(points).circle(r).extrude(t), then body.cut(...)."""

GUIDE_V3 = GUIDE_V2.replace("\n\nExamples:\n", "\n" + PLANE_NOTE + "\n\nExamples:\n") + "".join(
    f"\n\n# {name}\n{code}" for name, code in PLANE_EXAMPLES.items())


def evaluate(spec: dict, code: str, workdir: Path, reference: cq.Shape | None = None) -> list[dict]:
    """Run the code in the sandbox and check the part. An empty list means it passes."""
    run = runner.run(code, workdir)
    if run.category:
        return [violation(run.category, run.error)]
    try:
        return checker.check(spec, runner.load_step(run.step_path), reference or checker.reference_shape(spec))
    except Exception as e:  # OCC can fail on odd geometry; count it against the part, keep the reason
        return [violation("invalid_solid", f"the part could not be measured: {type(e).__name__}: {e}")]


def feedback(violations: list[dict], hints: bool = False) -> str:
    if not violations:
        return "PASS"
    lines = []
    for v in violations:
        lines.append(f"- {v['category']}: {v['message']}")
        if hints and v.get("hint"):
            lines.append(f"  hint: {v['hint']}")
    return "FAIL\n" + "\n".join(lines) + "\n" + RETRY


def history(attempts: list[dict]) -> str:
    """One line per earlier attempt, so the model sees a mistake it keeps repeating."""
    lines = [f"- attempt {a['attempt']}: " + (", ".join(a["categories"]) or "pass") for a in attempts]
    return ("Earlier attempts on this part:\n" + "\n".join(lines) +
            "\nIf the same failure repeats, build that feature a different way.")


def _code(call) -> str | None:
    try:
        code = json.loads(call.function.arguments)["code"]
    except (AttributeError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if not isinstance(code, str) or not code.strip():
        return None
    if code.lstrip().startswith("```"):  # some models fence the code even inside a tool call
        code = code.strip().removeprefix("```python").removeprefix("```").removesuffix("```")
    return code


def solve(spec: dict, llm, memory=None, max_attempts: int = 5, log=lambda record: None,
          guide: str | None = None) -> dict:
    """Work on one spec until it passes or the attempts run out. Returns the task record.

    guide (GUIDE for condition D, GUIDE_V2 for E): the system prompt carries the guide,
    the feedback carries the checker's hints, and a retry lists the earlier attempts' failures.
    """
    guided = guide is not None
    lessons = memory.relevant(spec["family"]) if memory else []
    prompt = spec["text"].strip()
    if lessons:
        prompt += "\n\nLessons from earlier parts:\n" + "\n".join(f"- {lesson}" for lesson in lessons)
    system = SYSTEM + "\n\n" + guide if guided else SYSTEM
    head = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    tail: list[dict] = []
    reference = checker.reference_shape(spec)
    attempts = []

    with tempfile.TemporaryDirectory() as tmp:
        for n in range(1, max_attempts + 1):
            start = time.perf_counter()
            try:
                message, usage = llm.chat(head + tail, tools=[RUN_AND_CHECK])
            except openai.BadRequestError as e:
                # The provider rejected the model's tool call as malformed (Groq words this
                # "tool_use_failed" or "Failed to parse tool call arguments"). It counts as an attempt.
                if "tool" not in str(e).lower():
                    raise
                message, usage = None, None
            model_seconds = time.perf_counter() - start

            call = message.tool_calls[0] if message is not None and message.tool_calls else None
            code = _code(call) if call else None
            start = time.perf_counter()
            if code is None:
                violations = [violation("no_code", "the reply was not a run_and_check call with a `code` argument")]
                tail = [{"role": "user", "content": "Call run_and_check with the complete script."}]
            else:
                violations = evaluate(spec, code, Path(tmp) / f"attempt_{n}", reference)
                result = feedback(violations, hints=guided)
                if guided and violations and attempts:
                    result += "\n\n" + history(attempts)
                tail = [
                    {"role": "assistant", "content": message.content or "", "tool_calls": [{
                        "id": call.id, "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments},
                    }]},
                    {"role": "tool", "tool_call_id": call.id, "content": result},
                ]
            record = {
                "attempt": n,
                "prompt": prompt if n == 1 else None,
                "code": code,
                "violations": violations,
                "categories": sorted({v["category"] for v in violations}),
                "passed": not violations,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "model_seconds": round(model_seconds, 2),
                "check_seconds": round(time.perf_counter() - start, 2),
            }
            attempts.append(record)
            log(record)
            if record["passed"]:
                break

    task = {
        "spec": spec["id"],
        "family": spec["family"],
        "difficulty": spec["difficulty"],
        "passed": attempts[-1]["passed"],
        "attempts": len(attempts),
        "lessons_in_prompt": len(lessons),
        "tokens": sum(a["prompt_tokens"] + a["completion_tokens"] for a in attempts),
    }
    if memory is not None and (len(attempts) > 1 or not task["passed"]):
        try:
            if lesson := memory.learn(llm, spec, attempts):
                task["lesson"] = lesson
                task["tokens"] += lesson.pop("tokens")
        except openai.BadRequestError as e:
            task["lesson"] = {"lesson": "", "kept": False, "refused": f"model error: {e}"}
    return task
