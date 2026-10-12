"""`Fn(A) -> R`: owned closure values that can be returned, stored, and shared."""
from pathlib import Path

from tests.helpers import messages, run_built

ROOT = Path(__file__).resolve().parents[1]


def test_owned_closures_example(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((ROOT / "examples" / "owned_closures.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["6 15", "-29", "ok 10", "5"]
    assert "LEAK" not in r.stderr


def test_calling_a_returned_or_indexed_function_value(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn make_adder(k: i32) -> Fn(i32) -> i32:
    f = fn(x: i32) -> i32 => x + k
    return f

fn twice(x: i32) -> i32:
    return x * 2

fn main():
    print(make_adder(2)(1))
    hs = List[Fn(i32) -> i32]()
    hs.push(make_adder(10))
    hs.push(twice)
    for i in 0..hs.len:
        print(hs[i](5))
    print(hs[0](1))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["3", "15", "10", "11"]
    assert "LEAK" not in r.stderr


def test_heap_capture_moves_into_fn():
    src = ("fn main():\n    name = string.from(\"a\")\n"
           "    f: Fn(i32) -> usize = fn(x: i32) -> usize => name.len()\n    print(f(1), name.len())\n")
    assert any("was moved" in m for m in messages(src))


def test_borrowing_closure_cannot_become_fn():
    src = ("fn mk(s: string) -> Fn(i32) -> usize:\n    f = fn(x: i32) -> usize => s.len()\n    return f\n\n"
           "fn main():\n    pass\n")
    assert any("cannot become a `Fn` value" in m for m in messages(src))


def test_fn_closure_cannot_change_its_copy():
    src = ("fn mk() -> Fn(i32):\n    out = List[i32]()\n    return fn(x: i32) => out.push(x)\n\n"
           "fn main():\n    pass\n")
    assert any("A `Fn` closure cannot change `out`" in m for m in messages(src))


def test_fn_is_not_a_plain_function_pointer():
    src = ("fn apply(f: fn(i32) -> i32) -> i32:\n    return f(1)\n\n"
           "fn main():\n    k = 1\n    g: Fn(i32) -> i32 = fn(x: i32) -> i32 => x + k\n    print(apply(g))\n")
    assert any("cannot be used where a plain" in m for m in messages(src))


def test_calling_a_non_function():
    assert any("is a `i32`, not a function" in m for m in messages("fn main():\n    x = 3\n    print(x(1))\n"))
