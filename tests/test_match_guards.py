"""`pattern if condition:` arms and `name if condition:` whole-value arms."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_guards_run(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "match_guards.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "0 zero", "-5 negative", "1 small odd", "2 medium", "3 small odd", "50 medium", "500 big",
        "big circle 20 circle 2 square 3 rect empty",
        "he-word hello",
        "abcd",
        "over five",
    ]


def test_consume_guard_moves_only_when_true(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
enum E:
    A(string)
    B

fn main():
    for t in ["hi", "a long one"]:
        e = E.A(t)
        match consume e:
            A(s) if s.len() > 5:
                print("long", s)
            A(s):
                print("short", s)
            B:
                pass
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["short hi", "long a long one"]


def test_guarded_arm_does_not_cover_its_variant():
    src = "enum E:\n    A(i32)\n    B\n\nfn main():\n    e = E.A(1)\n    match e:\n        A(x) if x > 0:\n            print(x)\n        B:\n            print(0)\n"
    _p, diags = front_end(src)
    assert [d.code for d in diags] == ["GG0222"]
    assert "does not count" in diags[0].hint


def test_guard_must_be_bool():
    _p, diags = front_end("fn main():\n    match 5:\n        v if v + 1:\n            pass\n        _:\n            pass\n")
    assert [d.code for d in diags] == ["GG0201"]


def test_unit_variant_with_guard_is_the_variant():
    src = """\
enum E:
    A
    B

fn main():
    flag = true
    for e in [E.A, E.B]:
        match e:
            A if flag:
                print("a")
            A:
                print("a, no flag")
            B:
                print("b")
"""
    assert run_built(src).stdout.splitlines() == ["a", "b"]
