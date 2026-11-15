"""Run CadQuery code in a separate process and load the part it builds.

Model-written code never runs in this process. `run` writes it to a temporary
folder and starts `_sandbox.py` with `python -I`, a time limit and an environment
that holds only what Python needs to start, so API keys never reach the code.

ponytail: no CPU, memory or network limits; Windows has no portable way to set
them from Python. A container is the upgrade if the agent ever runs untrusted specs.
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

SANDBOX = Path(__file__).with_name("_sandbox.py")
TIMEOUT = 30.0  # seconds
_ENV_KEEP = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE", "LOCALAPPDATA")


@dataclass
class RunResult:
    category: str | None  # None when a part was built, else syntax_error, runtime_error or timeout
    error: str
    step_path: Path | None
    seconds: float


def run(code: str, workdir: Path, timeout: float = TIMEOUT) -> RunResult:
    """Run `code` in a sandbox process; on success the part is at `step_path`."""
    try:
        compile(code, "part.py", "exec")  # compiling runs nothing
    except SyntaxError as e:
        return RunResult("syntax_error", f"line {e.lineno}: SyntaxError: {e.msg}", None, 0.0)

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "part.py").write_text(code, encoding="utf-8")
    step = workdir / "part.step"
    step.unlink(missing_ok=True)
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(SANDBOX), "part.py", step.name],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult("timeout", f"the code did not finish within {timeout:g} s", None, timeout)
    seconds = time.perf_counter() - start

    if proc.returncode != 0 or not step.exists():
        error = proc.stderr.strip()[:1000] or f"the sandbox exited with code {proc.returncode}"
        return RunResult("runtime_error", error, None, seconds)
    return RunResult(None, "", step, seconds)


def load_step(path: Path) -> cq.Shape:
    """Read a STEP file as one shape (a compound when it holds several)."""
    shapes = cq.importers.importStep(str(path)).vals()
    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def build_trusted(code: str) -> cq.Shape:
    """Build a part from this repository's own code (reference parts, tests).

    Runs in this process, so it is only for code written by us, never by the model.
    """
    namespace: dict = {}
    exec(compile(code, "reference.py", "exec"), namespace)
    result = namespace["result"]
    if isinstance(result, cq.Workplane):
        vals = result.vals()
        return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    return result
