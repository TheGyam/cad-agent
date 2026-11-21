"""The benchmark end to end with a scripted model: run, resume, analyse."""

from bench import analyze, run_bench
from bench.run_bench import read_jsonl
from agent import checker
from tests.test_loop import ScriptedModel

SPECS = {s["id"]: s for s in checker.load_specs()}


class FakeLLM(ScriptedModel):
    """Gets plate_02 wrong once, then right; gets plate_03 right first time."""

    model = "scripted"

    def __init__(self, seed=None):
        super().__init__([])

    def chat(self, messages, tools=None):
        if tools:
            spec = "plate_02" if "100 mm (X) by 60 mm" in messages[1]["content"] else "plate_03"
            ref = SPECS[spec]["reference"]
            first_try = len(messages) == 2
            self.replies = [ref.replace("hole(20)", "hole(22)") if spec == "plate_02" and first_try else ref]
        return super().chat(messages, tools)


def test_runs_resumes_and_analyses(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "not-used")
    monkeypatch.setattr(run_bench, "LLM", FakeLLM)
    args = ["--specs", "plate_02", "plate_03", "--out", str(tmp_path)]

    assert run_bench.main(args) == 0
    tasks = read_jsonl(tmp_path / "tasks.jsonl")
    assert sorted((t["condition"], t["spec"], t["attempts"]) for t in tasks) == [
        ("A", "plate_02", 2), ("A", "plate_03", 1), ("B", "plate_02", 2), ("B", "plate_03", 1)]
    assert len(read_jsonl(tmp_path / "attempts.jsonl")) == 6
    assert (tmp_path / "lessons_B_run0.json").exists()

    assert run_bench.main(args) == 0  # everything is done, so nothing runs again
    assert len(read_jsonl(tmp_path / "tasks.jsonl")) == 4

    assert analyze.main([str(tmp_path)]) == 0
    m = analyze.metrics(*analyze.load(tmp_path))
    assert m.loc["A", "pass rate"] == 1.0
    assert m.loc["A", "pass on 1st attempt"] == 0.5
    assert m.loc["A", "1st attempt ran but wrong"] == 0.5
    assert m.loc["A", "attempts to pass"] == 1.5
    assert "| Specs passed within 5 attempts | 100% | 100% |" in (tmp_path / "summary.md").read_text()
    assert (tmp_path / "pass_rate_by_family.png").exists() and (tmp_path / "failure_categories.png").exists()


def test_paired_test_uses_every_run_the_two_conditions_share():
    import pandas as pd

    rows = [("A", 0, "s1", False), ("D", 0, "s1", True), ("B", 0, "s1", True),
            ("A", 1, "s1", False), ("D", 1, "s1", True),  # B has no run 1; the pair must still count
            ("A", 1, "s2", True), ("D", 1, "s2", False)]
    tasks = pd.DataFrame(rows, columns=["condition", "run", "spec", "passed"])
    assert analyze.paired_test(tasks, "D")[:2] == (1, 2)
    assert analyze.paired_test(tasks, "B")[:2] == (0, 1)


def test_runs_specs_from_another_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "not-used")
    monkeypatch.setattr(run_bench, "LLM", FakeLLM)
    holdout = checker.SPEC_DIR / "holdout"
    assert run_bench.main(["--spec-dir", str(holdout), "--specs", "plate_h1", "--conditions", "A",
                           "--max-attempts", "1", "--out", str(tmp_path)]) == 0
    assert [t["spec"] for t in read_jsonl(tmp_path / "tasks.jsonl")] == ["plate_h1"]
