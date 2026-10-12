"""`gg new --template`, `gg run -e`, and `gg doctor`."""
import subprocess
import sys


def gg(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True, cwd=cwd)


def test_eval_prints_last_expression():
    r = gg("run", "-e", "x = 6\nx * 7")
    assert r.returncode == 0 and r.stdout.strip() == "42"


def test_eval_with_declarations():
    r = gg("run", "-e", "fn twice(a: i32) -> i32:\n    return a * 2\ntwice(4)")
    assert r.stdout.strip() == "8"


def test_templates_pass_their_own_tests(tmp_path):
    for t in ("bin", "lib", "cli"):
        assert gg("new", f"p_{t}", "--template", t, cwd=tmp_path).returncode == 0
        r = gg("test", ".", cwd=tmp_path / f"p_{t}")
        assert r.returncode == 0, r.stdout + r.stderr


def test_doctor_runs(tmp_path):
    r = gg("doctor", cwd=tmp_path)
    assert "gg " in r.stdout and "linker" in r.stdout
