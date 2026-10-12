"""End-to-end tests: compile with `python -m greengold run`, execute, compare stdout."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.skipif(
    shutil.which("gcc") is None and shutil.which("clang") is None,
    reason="gcc/clang not found")


def run_gg(path: Path):
    return subprocess.run(
        [sys.executable, "-m", "greengold", "run", str(path)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=60)


def run_source(tmp_path: Path, src: str):
    f = tmp_path / "prog.gg"
    f.write_text(src, encoding="utf-8")
    return run_gg(f)


def lines(result) -> list[str]:
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_hello():
    assert lines(run_gg(EXAMPLES / "hello.gg")) == ["Hello, Greengold!"]


def test_player_prints_75():
    assert lines(run_gg(EXAMPLES / "player.gg")) == ["75"]


def test_fibonacci():
    out = lines(run_gg(EXAMPLES / "fibonacci.gg"))
    assert out[:11] == ["0", "1", "1", "2", "3", "5", "8", "13", "21", "34", "55"]
    assert out[11] == "12586269025"  # i64


def test_modes_example():
    assert lines(run_gg(EXAMPLES / "modes.gg")) == ["2", "2", "11", "102", "102", "7"]


def test_modes_core(tmp_path):
    src = """struct Counter:
    value: i32

fn show(c: Counter):
    print(c.value)

fn bump(c: lend Counter):
    c.value += 1

fn finish(c: consume Counter):
    print(c.value)

fn main():
    c = Counter{ value: 0 }
    bump(c)
    bump(c)
    show(c)
    finish(c)
"""
    assert lines(run_source(tmp_path, src)) == ["2", "2"]
    bad = run_source(tmp_path, src + "    show(c)\n")
    assert bad.returncode == 1
    assert "`c` variable was moved (`consume`), can no longer be used." in bad.stderr
    assert "finish(c)" in bad.stderr  # move line is shown


def test_compile_error_exit_code_and_format(tmp_path):
    r = run_source(tmp_path, "fn main():\n    fixed x = 5\n    x = 6\n")
    assert r.returncode == 1
    assert "Error:" in r.stderr and "^" in r.stderr and "help:" in r.stderr
    assert "    x = 6" in r.stderr  # relevant source line
    assert "prog.gg:3:5" in r.stderr


def test_control_flow_and_arithmetic(tmp_path):
    src = """fn main():
    i = 0
    sum = 0
    while i < 10:
        i += 1
        if i % 2 == 0:
            continue
        elif i > 7:
            break
        else:
            sum += i
    print(sum)
    for k in 0..3:
        print(k * 2 + 1)
    for k in 0..=2:
        print(-k)
    print(7 / 2)
    print(7.0 / 2.0)
    print(1 + 2 * 3 - (4 - 6))
"""
    # i = 1,3,5,7 added (9 > 7 -> break); sum = 16

    assert lines(run_source(tmp_path, src)) == ["16", "1", "3", "5", "0", "-1", "-2", "3", "3.5", "9"]


def test_print_types(tmp_path):
    src = """fn main():
    a: i32 = -5
    b: i64 = 5000000000
    c: f32 = 1.5
    d: f64 = 2.25
    e = true
    f = false
    print(a)
    print(b)
    print(c)
    print(d)
    print(e)
    print(f)
    print("a b")
    print(1, true, "x")
    print(1 < 2, 3 >= 4)
"""
    assert lines(run_source(tmp_path, src)) == [
        "-5", "5000000000", "1.5", "2.25", "true", "false", "a b", "1 true x", "true false"]


def test_functions_and_returns(tmp_path):
    src = """fn add(a: i32, b: i32) -> i32:
    return a + b

fn fact(n: i64) -> i64:
    if n <= 1:
        return 1
    return n * fact(n - 1)

fn sign(x: i32) -> i32:
    if x < 0:
        return -1
    elif x == 0:
        return 0
    else:
        return 1

fn main():
    print(add(2, 3))
    print(fact(20))
    print(sign(-9), sign(0), sign(4))
"""
    assert lines(run_source(tmp_path, src)) == ["5", "2432902008176640000", "-1 0 1"]


def test_nested_structs_and_lend_field(tmp_path):
    src = """struct Vec2:
    x: f32
    y: f32

struct Body:
    pos: Vec2
    mass: f32

impl Vec2:
    fn add(self: lend Vec2, dx: f32, dy: f32):
        self.x += dx
        self.y += dy

impl Body:
    fn step(self: lend Body):
        self.pos.add(1.0, 2.0)

fn move(v: lend Vec2):
    v.x *= 2.0

fn main():
    b = Body{
        pos: Vec2{ x: 1.0, y: 1.0 }
        mass: 3.0
    }
    b.step()
    b.step()
    move(b.pos)
    print(b.pos.x)
    print(b.pos.y)
    print(b.mass)
"""
    assert lines(run_source(tmp_path, src)) == ["6", "5", "3"]


def test_give_param_is_mutable_and_reassign(tmp_path):
    src = """struct C:
    v: i32

fn eat(c: consume C):
    c.v += 10
    print(c.v)

fn main():
    c = C{ v: 1 }
    eat(c)
    c = C{ v: 5 }
    eat(c)
"""
    assert lines(run_source(tmp_path, src)) == ["11", "15"]


def test_method_on_lend_param_and_read_method(tmp_path):
    src = """struct C:
    v: i32

impl C:
    fn inc(self: lend C):
        self.v += 1

    fn get(self: C) -> i32:
        return self.v

    fn inc_twice(self: lend C):
        self.inc()
        self.inc()
        print(self.get())

fn main():
    c = C{ v: 0 }
    c.inc_twice()
    print(c.get())
"""
    assert lines(run_source(tmp_path, src)) == ["2", "2"]


def test_for_bound_evaluated_once(tmp_path):
    src = """fn main():
    n = 3
    count = 0
    for i in 0..n:
        n += 1
        count += 1
    print(count)
"""
    assert lines(run_source(tmp_path, src)) == ["3"]


def test_string_escapes(tmp_path):
    src = 'fn main():\n    print("tab\\there \\"q\\"")\n'
    assert lines(run_source(tmp_path, src)) == ['tab\there "q"']


def test_run_propagates_nothing_extra(tmp_path):
    r = run_source(tmp_path, "fn main():\n    print(1)\n")
    assert r.stderr == ""
