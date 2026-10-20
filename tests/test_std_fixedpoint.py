"""std.fixedpoint: Fx[S] numbers."""
from tests.helpers import run_gg_source

PROGRAM = r'''import std.fixedpoint { Fx }

fn main():
    a = Fx[16].from_int(3)
    b = Fx[16].from_f64(0.25)
    print(a.mul(b).to_f64(), a.add(b).to_f64(), a.sub(b).to_f64(), a.div(b).to_f64(), b.neg().to_f64())
    c = Fx[16].from_f64(-2.5)
    print(c.mul(a).to_f64(), c.div(a).to_f64(), c.floor_int(), c.round_int(), c.trunc_int(), c.abs().to_f64())
    print(Fx[16].from_int(2).sqrt().to_f64(), Fx[16].from_f64(144.0).sqrt().to_f64(), Fx[8].from_int(10).sqrt().to_f64())
    print(a.format(4), c.format(3), Fx[16].from_f64(3.14159).format(5))
    big = Fx[16].from_int(100000000000)
    print(big.saturating_mul(big).raw == max_value[i64](), a.lt(b), a.max(b).to_f64(), a.clamp(b, b).to_f64())
    print(Fx[31].from_f64(0.5).mul(Fx[31].from_f64(0.5)).to_f64())
'''


def test_fixed_point(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "0.75 3.25 2.75 12 -0.25",
        "-7.5 -0.833328247070312 -3 -3 -2 2.5",
        "1.41419982910156 12 3.16015625",
        "3.0000 -2.500 3.14158",
        "true false 3 0.25",
        "0.25",
    ]


def test_fixed_point_overflow_traps(tmp_path):
    src = """import std.fixedpoint { Fx }

fn main():
    big = Fx[16].from_int(100000000000)
    print(big.mul(big).raw)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode != 0 and "overflow" in r.stderr
