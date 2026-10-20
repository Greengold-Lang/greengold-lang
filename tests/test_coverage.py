"""`gg run --coverage`, `gg test --coverage`, `gg coverage`: statements, decisions, conditions, MC/DC.

Spec: 18
"""
import os
import subprocess
import sys

from greengold import coverage
from tests.helpers import ROOT

PROGRAM = """fn classify(a: i32, b: i32, flag: bool) -> i32:
    if a > 0 and (b > 0 or flag):
        return 1
    elif a < 0:
        return 2
    return 0

fn unused() -> i32:
    return 42

fn main():
    print(classify(1, 1, false), classify(1, -1, true), classify(1, -1, false), classify(-1, 0, false))
    i = 0
    while i < 3:
        i += 1
    print(i)
"""


def gg(*args, cwd, env=None):
    e = dict(os.environ)
    e.pop(coverage.ENV_ON, None)
    e.pop(coverage.ENV_OUT, None)
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True, cwd=cwd, env=e)


def _env():
    return {"PYTHONPATH": str(ROOT)}


def test_run_with_coverage_prints_the_summary(tmp_path):
    src = tmp_path / "app.gg"
    src.write_text(PROGRAM, encoding="utf-8")
    r = gg("run", str(src), "--coverage", cwd=tmp_path, env=_env())
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[:2] == ["1 1 0 2", "3"]
    assert "statements :  90.0%  (9/10)" in r.stdout
    assert "decisions  : 100.0%  (3/3)" in r.stdout
    assert "conditions : 100.0%  (5/5)" in r.stdout
    assert "MC/DC      : 100.0%  (5/5)" in r.stdout
    assert (tmp_path / ".gg-coverage").is_file()
    ann = gg("coverage", "--annotate", "--lcov", str(tmp_path / "out.info"), cwd=tmp_path, env=_env())
    assert ann.returncode == 0, ann.stderr
    assert "not executed:" in ann.stdout and ":8:" not in ann.stdout.split("not executed:")[0]
    assert any(line.endswith(":9:5:S") is False and ":9:" in line for line in ann.stdout.splitlines())
    lcov = (tmp_path / "out.info").read_text(encoding="utf-8")
    assert "SF:" in lcov and "DA:9,0" in lcov and "end_of_record" in lcov


def test_missing_vectors_show_as_gaps(tmp_path):
    src = tmp_path / "app.gg"
    src.write_text("""fn pick(a: bool, b: bool) -> i32:
    if a and b:
        return 1
    return 0

fn main():
    print(pick(true, true), pick(false, true))
""", encoding="utf-8")
    r = gg("run", str(src), "--coverage", cwd=tmp_path, env=_env())
    assert r.returncode == 0, r.stderr
    assert "decisions  : 100.0%  (1/1)" in r.stdout
    assert "MC/DC      :  50.0%  (1/2)" in r.stdout      # b was never decided on its own
    ann = gg("coverage", "--annotate", cwd=tmp_path, env=_env())
    assert "condition 2 has no MC/DC pair" in ann.stdout


def test_test_command_adds_coverage_across_tests(tmp_path):
    src = tmp_path / "lib.gg"
    src.write_text("""fn sign(x: i32) -> i32:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0

fn test_positive():
    require sign(5) == 1

fn test_negative():
    require sign(-5) == -1
""", encoding="utf-8")
    r = gg("test", str(src), "--coverage", cwd=tmp_path, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "test result: ok. 2 passed" in r.stdout
    assert "decisions  :  50.0%  (1/2)" in r.stdout     # `x > 0` saw both outcomes, `x < 0` only true
    assert "statements :" in r.stdout


def test_metrics_function_on_known_vectors():
    # a and b: runs (1,1)->1, (0,X)->0, (1,0)->0 encode each condition as 0, 1, or 2 (not evaluated), base 3
    def vec(a, b):
        return a + 3 * b
    seen = {vec(1, 1) * 2 + 1, vec(0, 2) * 2, vec(1, 0) * 2}
    both, cond, mcdc = coverage.decision_metrics(2, seen)
    assert both and cond == [True, True] and mcdc == [True, True]
    both, cond, mcdc = coverage.decision_metrics(2, {vec(1, 1) * 2 + 1, vec(0, 2) * 2})
    assert both and cond == [True, False] and mcdc == [True, False]
