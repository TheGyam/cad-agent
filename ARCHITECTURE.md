# Architecture

How the code is organised, and the rules that keep it that way.

## Where things live

```
specs/                One YAML file per benchmark part: the text the agent sees,
                      the constraints the checker uses, a reference part and
                      broken copies of it.
agent/
  llm.py                The model client (any OpenAI-compatible API) and the
                        run_and_check tool definition
  runner.py             Runs generated code in a sandbox process; loads STEP files
  _sandbox.py           The sandbox process itself. Never imported.
  checker.py            Loads specs and measures a part against one
  loop.py               Generate, run, check, feed back, up to 5 attempts; the
                        CadQuery guide that condition D adds to the prompt
  memory.py             Lessons: asked for, filtered, stored, put in the prompt
                        (v1 for condition B, the stricter v2 for C)
bench/
  run_bench.py          Runs all specs in each condition (A-D), logs to JSONL, resumes
  analyze.py            Turns a results folder into summary.md and plots
tests/                pytest. The checker tests run every spec's parts.
results/<model>/      Benchmark logs, lessons, summary and plots, kept in git.
```

## The flow

```
spec text + lessons → model → run_and_check(code)
                              → sandbox process → part.step
                              → checker → violations → back to the model
                       repeat until PASS or 5 attempts
                       → (conditions B, C) one lesson → lessons_<B|C>_run<r>.json
```

Each step hands the next one plain data: a spec dict, a code string, a STEP
file, a list of `{category, message}` violations, a task record.

## The rules

1. **Model-written code never runs in the agent's process.** It runs through
   `runner.run`: a separate `python -I` process in a temporary folder, with a time
   limit and an environment that holds no API keys. `runner.build_trusted` runs code
   in-process and is only for this repository's own reference parts.
2. **The checker is the ground truth, so it is tested first.** Every spec has a
   reference part that must pass and at least two broken copies that must fail
   with a named category (`tests/test_specs.py`). A change to the checker or a spec
   is not done until that file passes.
3. **Constraints are written twice.** The constraints in a spec are typed by hand
   from the text, independently of the reference code, and the reference must
   satisfy them. That is what catches a wrong reference part.
4. **Every failure has exactly one category** from `checker.CATEGORIES`. The
   analysis counts categories, so a new kind of failure means a new category, not
   a free-text message.
5. **Results come from logs only.** `analyze.py` reads `tasks.jsonl` and
   `attempts.jsonl` and nothing else, so every number in the README can be redone
   from the committed logs.
6. **Units are mm, positions are from the minimum corner.** The checker moves
   every part so its bounding box starts at the origin before measuring, so a part
   may be built anywhere, but its orientation must match the spec.

## Things worth knowing

- **Holes.** A hole is a concave cylindrical face, or several on the same axis and
  radius, that closes a full circle. Fillets and slot ends are concave too but never
  close a circle, so they are not holes. The depth is the hole wall's length along
  its axis; a chamfer at the mouth shortens it.
- **Wall thickness** is sampled: from a 5 x 5 grid on every flat face a ray goes
  into the material, and the distance to the next surface is the local thickness.
  Curved faces are skipped so bosses and hole walls do not count as walls.
- **The shape check** runs only when every named check passes. It compares the
  part with the reference by boolean difference and fails above 0.1% of the
  reference volume. It catches what the named checks cannot see, such as an
  enclosure open on the wrong side.
- **CadQuery's `hole()` resets the workplane.** After `.hole()`, the next feature is
  placed on the original plane, not the face selected before. Reference parts
  select the face again; plate_07 keeps the mistake as a broken copy.
- **Token budget.** Groq's free tier allows about 200K tokens a day per model. A
  retry sends only the spec, the lessons and the latest attempt with its result,
  not the whole conversation.
- **Condition D is guided, not learned.** It adds a hand-written CadQuery guide to the
  prompt, the checker's hints (where the separate solids are, which holes were found)
  to the feedback, and a one-line-per-attempt history to each retry. Every example in
  the guide is built and measured in `tests/test_loop.py`. Hints never change a
  violation's category, and conditions A-C never see them.
- **Lessons cannot carry answers.** A lesson that repeats any number from the spec
  text (other than 0 and 1) is refused, and so is one nearly the same as a kept one.
