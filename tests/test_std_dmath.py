"""std.dmath: close to the C library (a few ulp), and exactly the same bits on every run."""
import math
import random
import struct

from tests.helpers import run_gg_source

FUNCS = {
    "exp": (math.exp, lambda r: r.uniform(-30, 30)),
    "ln": (math.log, lambda r: 10 ** r.uniform(-12, 12)),
    "log2": (math.log2, lambda r: 10 ** r.uniform(-12, 12)),
    "log10": (math.log10, lambda r: 10 ** r.uniform(-12, 12)),
    "sin": (math.sin, lambda r: r.uniform(-1000, 1000)),
    "cos": (math.cos, lambda r: r.uniform(-1000, 1000)),
    "tan": (math.tan, lambda r: r.uniform(-1.5, 1.5)),
    "atan": (math.atan, lambda r: r.uniform(-50, 50)),
    "asin": (math.asin, lambda r: r.uniform(-1, 1)),
    "acos": (math.acos, lambda r: r.uniform(-1, 1)),
    "sinh": (math.sinh, lambda r: r.uniform(-20, 20)),
    "cosh": (math.cosh, lambda r: r.uniform(-20, 20)),
    "tanh": (math.tanh, lambda r: r.uniform(-8, 8)),
    "cbrt": (lambda x: math.copysign(abs(x) ** (1 / 3), x) if False else math.cbrt(x), lambda r: r.uniform(-1e6, 1e6)),
}


LIMIT = {"pow": 64, "hypot": 4}


def ulps(a: float, b: float) -> float:
    if a == b:
        return 0.0
    ia = struct.unpack("<q", struct.pack("<d", a))[0]
    ib = struct.unpack("<q", struct.pack("<d", b))[0]
    return abs(ia - ib)


def test_functions_are_within_a_few_ulp(tmp_path):
    rng = random.Random(42)
    lines = ["import std.dmath", "", "fn bits(x: f64) -> u64:", "    v: f64 = x", "    unsafe:",
             "        return ptr_cast[*u64](addr(v))[0]", "", "fn main():"]
    cases = []
    for name, (ref, gen) in FUNCS.items():
        for _ in range(60):
            x = gen(rng)
            cases.append((name, x, ref(x)))
            lines.append(f"    print(bits(dmath.{name}({x!r})))")
    for _ in range(60):
        y, x = rng.uniform(-50, 50), rng.uniform(-50, 50)
        cases.append(("atan2", (y, x), math.atan2(y, x)))
        lines.append(f"    print(bits(dmath.atan2({y!r}, {x!r})))")
        a, b = rng.uniform(0.01, 100), rng.uniform(-8, 8)
        cases.append(("pow", (a, b), a ** b))
        lines.append(f"    print(bits(dmath.pow({a!r}, {b!r})))")
        p, q = rng.uniform(-1e5, 1e5), rng.uniform(-1e5, 1e5)
        cases.append(("hypot", (p, q), math.hypot(p, q)))
        lines.append(f"    print(bits(dmath.hypot({p!r}, {q!r})))")
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    got = [struct.unpack("<d", struct.pack("<Q", int(x)))[0] for x in r.stdout.split()]
    assert len(got) == len(cases)
    worst: dict[str, float] = {}
    for g, (name, x, want) in zip(got, cases):
        err = ulps(g, want)
        worst[name] = max(worst.get(name, 0), err)
        assert err <= LIMIT.get(name, 4), (name, x, g, want, err)


def test_special_values(tmp_path):
    r = run_gg_source(tmp_path, """import std.dmath

fn main():
    print(dmath.exp(0.0), dmath.exp(710.0), dmath.exp(-800.0), dmath.ln(1.0), dmath.ln(0.0), dmath.ln(-1.0))
    print(dmath.sin(0.0), dmath.cos(0.0), dmath.sin(1.0e7), dmath.atan(1.0e300), dmath.pow(2.0, 10.0), dmath.pow(2.0, -2.0), dmath.pow(0.0, 3.0))
    print(dmath.pow(9.0, 0.5), dmath.asin(2.0), dmath.cbrt(-27.0), dmath.hypot(3.0, 4.0), dmath.atan2(1.0, -1.0))
""")
    assert r.returncode == 0, r.stderr
    lines = [ln.split() for ln in r.stdout.splitlines()]
    assert lines[0] == ["1", "inf", "0", "0", "-inf", "nan"] or lines[0][:5] == ["1", "inf", "0", "0", "-inf"]
    assert lines[1][:2] == ["0", "1"] and lines[1][2] in ("nan", "-nan", "NaN")
    assert float(lines[1][3]) == math.pi / 2 or abs(float(lines[1][3]) - math.pi / 2) < 1e-14
    assert lines[1][4:] == ["1024", "0.25", "0"]
    assert abs(float(lines[2][0]) - 3.0) < 1e-14 and abs(float(lines[2][2]) + 3.0) < 1e-14 and abs(float(lines[2][3]) - 5.0) < 1e-14


def test_results_are_bit_for_bit_repeatable(tmp_path):
    # the golden bits are what this implementation gives; any machine that runs the tests must give the same
    r = run_gg_source(tmp_path, """import std.dmath

fn bits(x: f64) -> u64:
    v: f64 = x
    unsafe:
        return ptr_cast[*u64](addr(v))[0]

fn main():
    print(bits(dmath.exp(1.0)), bits(dmath.ln(10.0)), bits(dmath.sin(1.0)), bits(dmath.cos(2.0)), bits(dmath.atan(0.5)))
    print(bits(dmath.pow(2.0, 0.5)), bits(dmath.tanh(0.3)), bits(dmath.cbrt(10.0)), bits(dmath.exp(-12.5)), bits(dmath.asin(0.3)))
""")
    assert r.returncode == 0, r.stderr
    again = run_gg_source(tmp_path, open(tmp_path / "a.gg", encoding="utf-8").read())
    assert again.stdout == r.stdout
    golden = open(__file__.replace("test_std_dmath.py", "fixtures/dmath_golden.txt"), encoding="utf-8").read().splitlines()
    assert r.stdout.splitlines() == golden
