"""Lambdas inside generic functions and methods of generic types use the type parameters."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_generic_closures(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "generic_closures.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["2 1 [11, 15] [2]", "0 1"]


def test_owned_and_owner_param_lambdas(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn adder[T: Num](k: T) -> Fn(T) -> T:
    return fn(x: T) -> T => x + k

fn ident[T](xs: List[T]) -> List[T]:
    return xs.map(fn(x: T) -> T => x)

struct Pair[A, B]:
    a: A
    b: B

impl Pair[A, B]:
    fn firsts(self, xs: List[A]) -> usize:
        return xs.count(fn(x: A) -> bool => true)

fn main():
    f = adder(10)
    g = adder(0.5)
    print(f(1), g(1.0))
    xs = List[u8]()
    xs.push(7)
    print(ident(xs))
    p = Pair{ a: 1, b: "s" }
    print(p.firsts(List[i32]()))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["11 1.5", "[7]", "0"]


def test_lambda_body_is_checked_against_bounds():
    src = "fn f[T](xs: List[T], k: T) -> List[T]:\n    return xs.map(fn(x: T) -> T => x + k)\n\nfn main():\n    pass\n"
    _p, diags = front_end(src)
    assert any("operator `+`" in d.message for d in diags)
