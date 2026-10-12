"""`==` and `hash` field by field on structs, enums, tuples, and lists; `Eq` and `Key` bounds accept them."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_structural_equality_and_hash(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "struct_equality.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "true false false",
        "true false",
        "true true false",
        "true false",
        "true false",
        "true true true",
        "true None",
        "true false true",
        'Valid("origin-ish") None',
    ]


def test_float_field_cannot_be_hashed_but_compares():
    src = "struct F:\n    x: f64\n\nfn main():\n    a = F{ x: 1.0 }\n    print(a == a, hash(a))\n"
    _p, diags = front_end(src)
    assert [d.code for d in diags] == ["GG0243"]
    assert "f64" in diags[0].message


def test_function_field_cannot_be_compared():
    src = ("struct G:\n    f: fn(i32) -> i32\n\nfn id(x: i32) -> i32:\n    return x\n\n"
           "fn main():\n    g = G{ f: id }\n    print(g == g)\n")
    _p, diags = front_end(src)
    assert [d.code for d in diags] == ["GG0231"]
    assert "eq" in diags[0].hint


def test_generic_eq_bound_still_rejects_unbounded_compare():
    _p, diags = front_end("fn same[T](a: T, b: T) -> bool:\n    return a == b\n\nfn main():\n    print(same(1, 2))\n")
    assert diags and diags[0].code in ("GG0231", "GG0230")


def test_eq_bound_accepts_structs():
    src = """\
struct P:
    x: i32

fn same[T: Eq](a: T, b: T) -> bool:
    return a == b

fn main():
    print(same(P{ x: 1 }, P{ x: 1 }), same(P{ x: 1 }, P{ x: 2 }))
"""
    assert run_built(src).stdout.strip() == "true false"
