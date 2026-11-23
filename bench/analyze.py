"""Turn a results folder into the summary table and plots used in the README.

    python -m bench.analyze results/openai_gpt-oss-120b

Writes summary.md, pass_rate_by_family.png and failure_categories.png into the
folder. Attempts of specs that never finished (a run stopped mid-spec) are left out.
"""

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from bench.run_bench import read_jsonl  # noqa: E402

DID_NOT_RUN = {"no_code", "syntax_error", "runtime_error", "timeout"}
CONDITIONS = {"A": "without memory", "B": "memory v1", "C": "memory v2", "D": "guided", "E": "guided v2"}
COLORS = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a", "D": "#eda100", "E": "#e87ba4"}  # categorical slots 1-5 of the validated palette
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dd"


def load(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    tasks = pd.DataFrame(read_jsonl(folder / "tasks.jsonl"))
    attempts = pd.DataFrame(read_jsonl(folder / "attempts.jsonl"))
    if tasks.empty:
        raise SystemExit(f"No finished specs in {folder}")
    attempts = attempts[attempts["task"].isin(tasks["task"])]
    return tasks, attempts


def metrics(tasks: pd.DataFrame, attempts: pd.DataFrame) -> pd.DataFrame:
    """One row per condition. Rates are means over runs; *_sd is the spread across runs."""
    first = attempts[attempts["attempt"] == 1].copy()
    first["did_not_run"] = first["categories"].map(lambda c: bool(DID_NOT_RUN & set(c)))
    first["ran_but_wrong"] = ~first["did_not_run"] & ~first["passed"]

    per_run = tasks.groupby(["condition", "run"]).agg(pass_rate=("passed", "mean"), specs=("spec", "count"))
    firsts = first.groupby(["condition", "run"]).agg(
        pass_at_1=("passed", "mean"), ran_but_wrong=("ran_but_wrong", "mean"), did_not_run=("did_not_run", "mean"))
    per_run = per_run.join(firsts)

    rows = {}
    for condition, g in per_run.groupby(level="condition"):
        t = tasks[tasks["condition"] == condition]
        rows[condition] = {
            "runs": len(g),
            "specs per run": g["specs"].mean(),
            "pass rate": g["pass_rate"].mean(),
            "pass rate sd": g["pass_rate"].std(ddof=1) if len(g) > 1 else float("nan"),
            "pass on 1st attempt": g["pass_at_1"].mean(),
            "1st attempt ran but wrong": g["ran_but_wrong"].mean(),
            "1st attempt did not run": g["did_not_run"].mean(),
            "attempts to pass": t.loc[t["passed"], "attempts"].mean(),
            "rejected tool calls": attempts.loc[attempts["condition"] == condition, "categories"]
                                   .map(lambda c: "no_code" in c).mean(),
            "tokens per spec": t["tokens"].mean(),
        }
    return pd.DataFrame(rows).T


def paired_test(tasks: pd.DataFrame, condition: str, baseline: str = "A") -> tuple[int, int, float]:
    """Specs passed only in the baseline, only in `condition`, and the exact McNemar p-value.

    Pairs each spec with itself across conditions (same run), so only specs whose
    outcome differs carry information.
    """
    # Drop only pairs missing from these two conditions: other conditions may have fewer runs.
    passed = tasks.pivot_table(index=["run", "spec"], columns="condition", values="passed")[[baseline, condition]].dropna()
    only_base = int((passed[baseline].astype(bool) & ~passed[condition].astype(bool)).sum())
    only_cond = int((~passed[baseline].astype(bool) & passed[condition].astype(bool)).sum())
    n, k = only_base + only_cond, min(only_base, only_cond)
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return only_base, only_cond, p


def final_failures(tasks: pd.DataFrame, attempts: pd.DataFrame) -> pd.DataFrame:
    """For each spec that failed, the first category of its last attempt."""
    last = attempts.sort_values("attempt").groupby("task").tail(1).set_index("task")
    failed = tasks[~tasks["passed"]].copy()
    failed["category"] = failed["task"].map(lambda t: last.loc[t, "categories"][0])
    return failed


def _style(ax, grid_axis: str):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED, length=0)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_pass_rate_by_family(tasks: pd.DataFrame, path: Path) -> None:
    rates = tasks.groupby(["family", "condition"])["passed"].mean().unstack("condition") * 100
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    width = 0.78 / len(rates.columns)
    for i, condition in enumerate(rates.columns):
        x = [k + (i - (len(rates.columns) - 1) / 2) * (width + 0.02) for k in range(len(rates))]
        bars = ax.bar(x, rates[condition], width, color=COLORS[condition], label=CONDITIONS[condition])
        ax.bar_label(bars, fmt="%.0f%%", color=INK, fontsize=8, padding=2)
    ax.set_xticks(range(len(rates)), rates.index, color=INK)
    ax.set_ylim(0, 110)
    ax.set_ylabel("specs passed within 5 attempts (%)", color=MUTED)
    _style(ax, "y")
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncols=len(rates.columns), labelcolor=INK)
    ax.set_title("Pass rate by part family", loc="left", color=INK, fontsize=11, pad=28)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_failure_categories(attempts: pd.DataFrame, tasks: pd.DataFrame, path: Path) -> None:
    """How often each category shows up in failed attempts, per run, by condition."""
    runs = tasks.groupby("condition")["run"].nunique()
    exploded = attempts[~attempts["passed"]].explode("categories")
    counts = exploded.groupby(["categories", "condition"]).size().unstack("condition", fill_value=0) / runs
    counts = counts.loc[counts.sum(axis=1).sort_values().index]
    fig, ax = plt.subplots(figsize=(7, 0.2 * len(counts) * len(counts.columns) + 1.2), dpi=150)
    height = 0.78 / len(counts.columns)
    for i, condition in enumerate(counts.columns):
        y = [k - (i - (len(counts.columns) - 1) / 2) * (height + 0.02) for k in range(len(counts))]  # A on top
        ax.barh(y, counts[condition], height, color=COLORS[condition], label=CONDITIONS[condition])
    ax.set_yticks(range(len(counts)), counts.index, color=INK)
    ax.set_xlabel("attempts", color=MUTED)
    _style(ax, "x")
    ax.legend(frameon=False, loc="lower right", labelcolor=INK)
    ax.set_title("Failure categories in failed attempts (per run)", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def summary_markdown(m: pd.DataFrame, failures: pd.DataFrame, model: str, tasks: pd.DataFrame | None = None) -> str:
    def pct(v):
        return "n/a" if pd.isna(v) else f"{100 * v:.0f}%"

    def sd(v):
        return "" if pd.isna(v) else f" ± {100 * v:.0f}"

    cols = [c for c in CONDITIONS if c in m.index]
    runs = ", ".join(f"{CONDITIONS[c]} {int(m.loc[c, 'runs'])}" for c in cols)
    lines = [f"Model: `{model}`, {int(m['specs per run'].max())} specs per run. Runs: {runs}.", "",
             "| Metric | " + " | ".join(CONDITIONS[c] for c in cols) + " |",
             "|---|" + "---|" * len(cols)]
    rows = [
        ("Specs passed within 5 attempts", lambda c: pct(m.loc[c, "pass rate"]) + sd(m.loc[c, "pass rate sd"])),
        ("Passed on the first attempt", lambda c: pct(m.loc[c, "pass on 1st attempt"])),
        ("First attempt ran but was wrong", lambda c: pct(m.loc[c, "1st attempt ran but wrong"])),
        ("First attempt did not run", lambda c: pct(m.loc[c, "1st attempt did not run"])),
        ("Mean attempts, specs that passed", lambda c: f"{m.loc[c, 'attempts to pass']:.2f}"),
        ("Attempts rejected as malformed tool calls", lambda c: pct(m.loc[c, "rejected tool calls"])),
        ("Tokens per spec", lambda c: f"{m.loc[c, 'tokens per spec']:,.0f}"),
    ]
    lines += [f"| {name} | " + " | ".join(f(c) for c in cols) + " |" for name, f in rows]
    if tasks is not None and "A" in cols:
        lines += ["", "Paired by spec against the run without memory (exact McNemar test):", ""]
        for c in cols[1:]:
            only_a, only_c, p = paired_test(tasks, c)
            lines.append(f"- {CONDITIONS[c]}: {only_a} passed only without memory, "
                         f"{only_c} only with it, p = {p:.3f}")
    lines += ["", "Most frequent failure in specs that still failed, by condition:", ""]
    for c in cols:
        top = failures[failures["condition"] == c]["category"].value_counts()
        text = ", ".join(f"`{k}` ({v})" for k, v in top.items()) or "none"
        lines.append(f"- {CONDITIONS[c]}: {text}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    folder = Path((argv or sys.argv[1:])[0])
    tasks, attempts = load(folder)
    m = metrics(tasks, attempts)
    text = summary_markdown(m, final_failures(tasks, attempts), tasks["model"].iloc[0], tasks)
    (folder / "summary.md").write_text(text, encoding="utf-8")
    plot_pass_rate_by_family(tasks, folder / "pass_rate_by_family.png")
    plot_failure_categories(attempts, tasks, folder / "failure_categories.png")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
