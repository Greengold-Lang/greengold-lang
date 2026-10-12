"""Constant parameters: `fn total[N: usize](xs: [N]i32)`, `struct Grid[W: usize, H: usize]`."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_const_generics_run():
    r = run_built((EXAMPLES_DIR / "const_generics.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["6 10 4", "6 [[0, 0, 0], [0, 0, 7]]", "8"]


def test_struct_literal_and_methods_read_the_length():
    src = """\
struct Vec[N: usize]:
    v: [N]f64

impl Vec[N]:
    fn dot(self, other: Vec[N]) -> f64:
        s = 0.0
        for i in 0..N:
            s += self.v[i] * other.v[i]
        return s

fn main():
    a = Vec{ v: [1.0, 2.0, 3.0] }
    b = Vec[3]{ v: [4.0, 5.0, 6.0] }
    print(a.dot(b))
"""
    assert run_built(src).stdout.strip() == "32"


def _messages(src):
    return [d.message for d in front_end(src)[1]]


def test_errors():
    src = """\
fn dot[N: usize](a: [N]f64, b: [N]f64) -> f64:
    return 0.0

fn bad[N: usize](x: N) -> i32:
    return 0

fn bad2[N: usize + Ord](x: i32) -> i32:
    return x

struct Pair[A, B]:
    a: A
    b: B

fn main():
    print(dot([1.0, 2.0], [3.0, 4.0, 5.0]))
    print(dot[i32]([1.0], [1.0]))
    p: Pair[3, i32] = Pair[3, i32]{ a: 1, b: 2 }
"""
    msgs = _messages(src)
    assert any("is a constant parameter (a number), not a type" in m for m in msgs)
    assert any("takes one integer type" in m for m in msgs)
    assert any("inferred as both 2 and 3" in m for m in msgs)
    assert any("but `i32` is a type" in m for m in msgs)
    assert any("but `3` is a number" in m for m in msgs)


def test_value_must_fit_the_type():
    msgs = _messages("struct B[N: u8]:\n    x: [N]i32\n\nfn main():\n    b: B[300] = B[300]{ x: [0; 300] }\n")
    assert any("does not fit in `u8`" in m for m in msgs)
