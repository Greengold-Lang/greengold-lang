"""f16: half-precision numbers, converted through integer code (no runtime library needed)."""
import random
import struct

from tests.helpers import run_gg_source


def half(x: float) -> float:
    try:
        return struct.unpack("<e", struct.pack("<e", x))[0]
    except OverflowError:
        return float("inf") if x > 0 else float("-inf")


def test_f16_rounding_matches_ieee(tmp_path):
    rng = random.Random(7)
    values = [0.0, 1.0, -1.5, 65504.0, 65520.0, 1e-8, 6e-8, 5.960464477539063e-08, 3e-5, 0.1, 1 / 3, 2049.0, 2050.0,
              2051.0, 1e5, -1e5] + [rng.uniform(-70000, 70000) for _ in range(40)] + [10 ** rng.uniform(-9, 5) for _ in range(40)]
    values = [struct.unpack("<f", struct.pack("<f", v))[0] for v in values]  # an f32 goes in, so the same bits reach f16
    body = "".join(f"    print(f64(f16(f32({v!r}))))\n" for v in values)
    r = run_gg_source(tmp_path, "fn main():\n" + body)
    assert r.returncode == 0, r.stderr
    got = [float(x) for x in r.stdout.split()]
    want = [half(v) for v in values]
    assert len(got) == len(want)
    for g, w, v in zip(got, want, values):
        assert g == w or abs(g - w) <= abs(w) * 1e-14, (v, g, w)


def test_f16_arithmetic(tmp_path):
    r = run_gg_source(tmp_path, """fn main():
    a: f16 = 1.5
    b: f16 = 2.25
    c = a * b + 0.5
    print(c, a < b, -c, f32(c) + 1.0, i32(c))
    xs: [3]f16 = [1.0, 2.0, 0.5]
    t: f16 = 0.0
    for x in xs:
        t += x
    print(t, f"{t}")
    big: f16 = 60000.0
    print(big * 2.0)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["3.875 true -3.875 4.875 3", "3.5 3.5", "inf"]
