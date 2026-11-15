from agent import runner

BOX = "import cadquery as cq\nresult = cq.Workplane().box(10, 20, 30)\n"


def test_builds_a_part(tmp_path):
    r = runner.run(BOX, tmp_path)
    assert r.category is None, r.error
    assert runner.load_step(r.step_path).BoundingBox().zlen == 30


def test_syntax_error_is_caught_without_running(tmp_path):
    r = runner.run("result = (", tmp_path)
    assert r.category == "syntax_error"
    assert not (tmp_path / "part.py").exists()


def test_runtime_error_names_the_line(tmp_path):
    r = runner.run("import cadquery as cq\n\nresult = cq.Workplane().box(1, 1, 1).faces('>Q')\n", tmp_path)
    assert r.category == "runtime_error"
    assert r.error.startswith("line 3")


def test_missing_result_is_a_runtime_error(tmp_path):
    r = runner.run("import cadquery as cq\npart = cq.Workplane().box(1, 1, 1)\n", tmp_path)
    assert r.category == "runtime_error"
    assert "result" in r.error


def test_timeout(tmp_path):
    r = runner.run("while True:\n    pass\n", tmp_path, timeout=3)
    assert r.category == "timeout"


def test_api_keys_do_not_reach_the_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    code = "import os\nassert 'GROQ_API_KEY' not in os.environ\n" + BOX
    assert runner.run(code, tmp_path).category is None
