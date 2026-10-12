"""`{x:spec}` in f-strings (Core `_fmt_*` helpers) and exponent float literals."""
from pathlib import Path

import pytest

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_format_specs(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "format_specs.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "[3.14] [3] [   3.142] [3.1     |] [-3.142] [+3.1]",
        "[ff] [FF] [0xff] [11111111] [377] [11111111] [0x00ff]",
        "[  255] [255  ] [  255  ] [***255] [+255] [-00255] [-ff]",
        "[ab    ] [    ab] [  ab  ] [--ab---] [  şğ]",
        "[1.234568e+04] [1.23e-04] [1.000000E+00] [0.0e+00] [1.00e+01]",
        "[  xyz] [  P { x: 1 }] [  true] [0.300]",
        "apple       1.50",
        "kiwi       12.25",
    ]


def test_extreme_values():
    src = """\
fn main():
    big = max_value[i64]()
    small = min_value[i64]()
    print(f"{small:x} {big:#X} {max_value[u64]():b}")
    print(f"{-0.0001:.2} {0.995:.2} {1e300:.1} {1.5e-7:.3e}")
"""
    out = run_built(src).stdout.splitlines()
    assert out[0] == "-8000000000000000 0X7FFFFFFFFFFFFFFF " + "1" * 64
    assert out[1].split()[0] == "0.00"
    assert out[1].split()[1] in ("0.99", "1.00")
    assert out[1].split()[3] == "1.500e-07"


@pytest.mark.parametrize("spec, word", [
    (".2", "decimals"), ("x", "base"), ("+", "numbers"), ("zz", "not a format"), ("<05", "alignment"),
])
def test_bad_formats(spec, word):
    src = 'fn main():\n    n = 5\n    s = "a"\n    print(f"{%s:%s}")\n' % ("s" if spec in ("x", "+") else "n", spec)
    _p, diags = front_end(src)
    assert [d.code for d in diags] == ["GG0244"]
    assert word in diags[0].message


def test_text_after_the_expression_is_reported():
    _p, diags = front_end('fn main():\n    n = 5\n    print(f"{n m}")\n')
    assert diags and "Unexpected" in diags[0].message


def test_exponent_literals():
    src = "fn main():\n    a = 1e3\n    b = 2.5E-2\n    c: f32 = 4e0\n    print(a, b, c, 1_000e-3)\n"
    assert run_built(src).stdout.strip() == "1000 0.025 4 1"
