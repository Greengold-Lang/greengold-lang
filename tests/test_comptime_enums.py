"""`comptime fn` with enums and `match`; enum constants."""
from pathlib import Path

from tests.helpers import run_built

ROOT = Path(__file__).resolve().parents[1]


def test_comptime_enums_and_match():
    r = run_built((ROOT / "examples" / "comptime_enums.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "42 -5 [0, 1, -1, 2] Valid(10) None Op.Neg(9)"


def test_enum_constant_with_float_and_struct_payload():
    src = """\
struct P:
    x: i16
    y: f32

enum S:
    Dot(P)
    Circle(f64, u8)

const D = S.Dot(P{ x: -3, y: 2.5 })
const C = S.Circle(1.25, 200)

fn main():
    print(D, C)
"""
    r = run_built(src)
    assert r.stdout.strip() == "S.Dot(P { x: -3, y: 2.5 }) S.Circle(1.25, 200)", r.stderr
