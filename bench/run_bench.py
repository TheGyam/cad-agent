"""Run the benchmark: every spec without memory (A), with memory v1 (B) or v2 (C), or
guided (D: a CadQuery guide in the prompt, hints in the feedback, attempt history;
E: the same with guide v2, which adds round parts).

Every attempt is appended to attempts.jsonl and every finished spec to
tasks.jsonl in the output folder. Running the same command again skips the specs
already finished, so a run stopped by the daily token limit carries on where it
stopped. Run r shuffles the specs with seed r, and every condition uses that order.

    python -m bench.run_bench --runs 1
    python -m bench.run_bench --runs 1 --conditions D
    python -m bench.run_bench --runs 3 --conditions B --specs plate_01 flange_02
    python -m bench.run_bench --runs 3 --conditions AD --spec-dir specs/holdout --out results/holdout
"""

import argparse
import json
import os
import random
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import openai

from agent import checker, loop
from agent.llm import LLM
from agent.memory import Memory


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=1, help="runs per condition (default 1)")
    parser.add_argument("--conditions", default="AB", help="A = no memory, B = memory v1, C = memory v2, D = guided, E = guided v2 (default AB)")
    parser.add_argument("--specs", nargs="*", help="only these spec ids")
    parser.add_argument("--spec-dir", type=Path, default=checker.SPEC_DIR, help="folder of spec files (default specs/)")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--out", type=Path, help="results folder (default results/<model>)")
    args = parser.parse_args(argv)

    if not (os.environ.get("CAD_AGENT_API_KEY") or os.environ.get("GROQ_API_KEY")):
        print("Set GROQ_API_KEY (or CAD_AGENT_API_KEY) first. See the README.", file=sys.stderr)
        return 1
    if not args.conditions or set(args.conditions) - set("ABCDE"):
        parser.error("--conditions takes letters from A, B, C, D and E")

    specs = checker.load_specs(args.spec_dir)
    if not specs:
        parser.error(f"no spec files in {args.spec_dir}")
    if args.specs:
        specs = [s for s in specs if s["id"] in args.specs]
    model = LLM().model
    out = args.out or Path("results") / re.sub(r"[^\w.-]+", "_", model)
    out.mkdir(parents=True, exist_ok=True)
    done = {(t["condition"], t["run"], t["spec"]) for t in read_jsonl(out / "tasks.jsonl")}

    for run in range(args.runs):
        llm = LLM(seed=run)
        order = sorted(specs, key=lambda s: s["id"])
        random.Random(run).shuffle(order)
        for condition in args.conditions:
            lessons = out / f"lessons_{condition}_run{run}.json"
            memory = {"A": None, "B": Memory(lessons), "C": Memory(lessons, strict=True), "D": None, "E": None}[condition]
            for spec in order:
                if (condition, run, spec["id"]) in done:
                    continue
                meta = {"task": uuid.uuid4().hex, "condition": condition, "run": run,
                        "spec": spec["id"], "model": model}
                print(f"run {run} {condition} {spec['id']:<13}", end=" ", flush=True)
                try:
                    task = loop.solve(spec, llm, memory, args.max_attempts,
                                      log=lambda a: append_jsonl(out / "attempts.jsonl", {**meta, **a}),
                                      guide={"D": loop.GUIDE, "E": loop.GUIDE_V2}.get(condition))
                except openai.RateLimitError as e:
                    print(f"\nRate limit reached ({e.message}).\nRun the same command again later to carry on.")
                    return 2
                finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
                append_jsonl(out / "tasks.jsonl", {**meta, **task, "finished": finished})
                print(("pass" if task["passed"] else "FAIL") + f" in {task['attempts']}, {task['tokens']} tokens")
    print(f"Done. Next: python -m bench.analyze {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
