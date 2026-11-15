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


def evaluate(spec: dict, code: str, workdir: Path, reference: cq.Shape | None = None) -> list[dict]:
    """Run the code in the sandbox and check the part. An empty list means it passes."""
    run = runner.run(code, workdir)
    if run.category:
        return [violation(run.category, run.error)]
    try:
        return checker.check(spec, runner.load_step(run.step_path), reference or checker.reference_shape(spec))
    except Exception as e:  # OCC can fail on odd geometry; count it against the part, keep the reason
        return [violation("invalid_solid", f"the part could not be measured: {type(e).__name__}: {e}")]


def feedback(violations: list[dict]) -> str:
    if not violations:
        return "PASS"
    return "FAIL\n" + "\n".join(f"- {v['category']}: {v['message']}" for v in violations) + "\n" + RETRY


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


def solve(spec: dict, llm, memory=None, max_attempts: int = 5, log=lambda record: None) -> dict:
    """Work on one spec until it passes or the attempts run out. Returns the task record."""
    lessons = memory.relevant(spec["family"]) if memory else []
    prompt = spec["text"].strip()
    if lessons:
        prompt += "\n\nLessons from earlier parts:\n" + "\n".join(f"- {lesson}" for lesson in lessons)
    head = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
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
                tail = [
                    {"role": "assistant", "content": message.content or "", "tool_calls": [{
                        "id": call.id, "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments},
                    }]},
                    {"role": "tool", "tool_call_id": call.id, "content": feedback(violations)},
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
