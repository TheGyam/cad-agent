"""Entry point of the sandbox process. Never imported by the agent.

`runner.run` starts this file with `python -I`, inside a temporary folder and with
a stripped environment. It runs part.py and exports the variable `result` as STEP.
On failure it prints one short error line, pointing at the line in part.py.
"""

import sys
import traceback


def main(src_path: str, step_path: str) -> None:
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    namespace = {"__name__": "__main__"}
    # Track the line of part.py being run. Tracebacks can't be trusted for this:
    # pyparsing, which CadQuery uses for selectors, strips them.
    current = [0]

    def trace(frame, event, arg):
        if frame.f_code.co_filename != "part.py":
            return None

        def line(frame, event, arg):
            if event == "line":
                current[0] = frame.f_lineno
            return line

        return line

    sys.settrace(trace)
    try:
        exec(compile(src, "part.py", "exec"), namespace)
        sys.settrace(None)
        import cadquery as cq

        result = namespace.get("result")
        if result is None:
            raise NameError("the code must assign the finished part to a variable named `result`")
        if not isinstance(result, (cq.Workplane, cq.Shape)):
            raise TypeError(f"`result` must be a cadquery Workplane or Shape, not {type(result).__name__}")
        cq.exporters.export(result, step_path)
    except BaseException as exc:  # SystemExit too: the parent only needs the message
        sys.settrace(None)
        lines = src.splitlines()
        where = f"line {current[0]} ({lines[current[0] - 1].strip()}): " if 0 < current[0] <= len(lines) else ""
        sys.stderr.write(where + "".join(traceback.format_exception_only(exc)).strip())
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
