# cad-agent

An LLM agent that writes [CadQuery](https://github.com/CadQuery/cadquery) code
from a written part spec, a checker that measures the solid it builds, and a
memory of lessons from earlier mistakes. A 30-part benchmark measures whether the
memory helps.

## The problem: "it runs" is not "it's right"

Ask a language model for CAD code and it usually writes something that runs and
exports a solid. Whether that solid is the part you asked for is another
question: a hole 5 mm off, drilled from the wrong face or stopping halfway, an
enclosure open on the wrong side. None of these raise an error. You only find
them by measuring the part.

So this project treats the checker as the ground truth and builds it first. The
agent only gets told what the checker measured, with numbers:

```
FAIL
- hole_position: expected a 6.5 mm hole along Z at (45.0, 15.0); the nearest such hole is at (40.0, 15.0)
- hole_depth: the 6.6 mm hole along Z at (10.0, 10.0) is 4.0 mm deep, expected 8 mm
```

## How it works

```
            ┌──────────── spec text + up to 10 lessons ────────────┐
            ▼                                                      │
      ┌───────────┐  run_and_check(code)  ┌─────────────────────┐  │
      │   model   │ ────────────────────▶ │ sandbox process     │  │
      │ (tool     │                       │ python -I, 30 s,    │  │
      │  calling) │                       │ no API keys in env  │  │
      └───────────┘                       └─────────┬───────────┘  │
            ▲                                       │ part.step    │
            │        violations, with numbers       ▼              │
            └──────────────────────────────── ┌───────────┐        │
                     up to 5 attempts         │  checker  │        │
                                              └─────┬─────┘        │
                       needed fixes or failed?      │              │
                       ask for one general lesson ──┴─▶ memory ────┘
```

- **Model.** Groq's free `openai/gpt-oss-120b`, through any OpenAI-compatible
  API, so changing the model means changing one environment variable. The model
  gets one tool, `run_and_check`. Each call is one attempt.
- **Sandbox.** Generated code never runs inside the agent. It runs in its own
  `python -I` process in a temporary folder, with a 30 s limit and an
  environment stripped of API keys.
- **Checker** ([agent/checker.py](agent/checker.py)). It checks that the part is
  one valid solid, then its bounding box (±0.1 mm), volume (±1%), every hole
  (count, diameter, position, depth and direction, found from the cylindrical
  faces) and minimum wall thickness (by ray casting). If all of those pass, it
  compares the part with a hand-written reference part by boolean difference, to
  catch what the named checks cannot see.
- **Memory** ([agent/memory.py](agent/memory.py)). After a part that needed fixes
  or failed, the model writes one general lesson. A lesson that repeats any number
  from the spec is refused, so memory cannot carry answers, and so is one nearly
  the same as a lesson already kept. Up to 10 go into each prompt, same part
  family first. No vector database.

## The benchmark

30 specs in [specs/](specs), each tagged easy, medium or hard:

| Family | Count | What they test |
|---|---|---|
| Plates | 10 | outer size, hole patterns, chamfers, fillets, pockets, slots |
| L-brackets | 8 | two legs, holes on a specific face, fillets, gussets, slots |
| Flanges | 6 | bolt circles, bores, hubs, chamfered bores |
| Enclosures | 6 | shells, open faces, bosses with blind holes, rebates |

Each spec has the text the agent sees, the machine-checkable constraints, a
hand-written reference part, and broken copies of that part:

```yaml
id: bracket_01
text: >
  L-bracket made of 4 mm plate, 30 mm wide (Y). The horizontal leg lies on the
  XY plane and is 60 mm long in X. ...
constraints:
  bbox: [60, 30, 40]
  thickness_min: 4
  holes:
    - {d: 6.5, depth: 4, axis: z, at: [[15, 15], [45, 15]]}
broken:
  - {expect: wrong_face, replace: [...]}   # holes moved to the vertical leg
```

**How the checker was validated.** Before any model output was judged, all 30
reference parts pass the checker, and all 61 broken copies fail it with the
expected category: wrong face, wrong depth, a chamfer on the wrong side, an
enclosure open on the wrong face, and so on. The constraints are typed from the
text separately from the reference code, so a wrong reference is caught too.
That happened while building the benchmark: CadQuery's `.hole()` puts the next
feature back on the original workplane, so two references had holes that stopped
partway. The hole-depth check caught them, and plate_07 keeps that mistake as a
broken copy.

**Conditions.** A: no memory. B: memory builds up over the run, starting empty.
The same 30 specs in the same shuffled order for both conditions, temperature
1.0, seeded per run.

## Results

> **Not run yet.** The table below is filled in from `results/<model>/summary.md`
> once the benchmark has run. No number in this README comes from anywhere else.

| Metric | Without memory | With memory |
|---|---|---|
| Specs passed within 5 attempts | — | — |
| Passed on the first attempt | — | — |
| First attempt ran but was wrong | — | — |
| Mean attempts, specs that passed | — | — |

<!-- After a run: results/<model>/pass_rate_by_family.png and failure_categories.png -->

## Failure analysis

To be written from the logs after the run: the failure categories by condition,
which ones memory reduced, and the most frequent failure that remained.

## Limits and next ideas

- **One model, small benchmark.** 30 specs and a few runs give wide error bars;
  the spread across runs is reported for that reason.
- **The sandbox limits time, not resources.** There is no memory or network cap,
  because Windows has no portable way to set one from Python. A container would.
- **Wall thickness is sampled**, 25 points per flat face. A wall that is thin only
  between sample points is missed.
- **Lessons are ranked by family and recency, not similarity.** That is enough
  for tens of lessons, not hundreds.
- **Next fix: a `query_faces` tool.** Many CAD mistakes are about which face a
  feature lands on. A tool that lists the faces of the current part and their
  directions, called before placing features, should cut `wrong_face` and
  `hole_position` failures. Re-running the hard specs would show whether it does.

## How to run it

Python 3.11 or newer.

```bash
pip install -e ".[dev]"
pytest
```

The tests need no API key. They run every reference and broken part through the
checker, and the agent loop and benchmark with a scripted model.

To run the benchmark, get a free API key from https://console.groq.com and set it:

```bash
export GROQ_API_KEY=...            # PowerShell: $env:GROQ_API_KEY = "..."
python -m bench.run_bench --runs 1
python -m bench.analyze results/openai_gpt-oss-120b
```

One condition-run of 30 specs uses roughly a day of Groq's free token budget. If
the limit is reached, the run stops with a message; run the same command again
later and it carries on from where it stopped.

Other models: set `CAD_AGENT_BASE_URL`, `CAD_AGENT_MODEL` and `CAD_AGENT_API_KEY`
for any OpenAI-compatible API (see [agent/llm.py](agent/llm.py)).

How the code is organised: [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT
