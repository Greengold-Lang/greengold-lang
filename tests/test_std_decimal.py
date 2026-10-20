"""std.decimal against Python's decimal module."""
import decimal
import random

from tests.helpers import run_gg_source

MODES = {"HALF_EVEN": decimal.ROUND_HALF_EVEN, "HALF_UP": decimal.ROUND_HALF_UP, "HALF_DOWN": decimal.ROUND_HALF_DOWN,
         "UP": decimal.ROUND_UP, "DOWN": decimal.ROUND_DOWN, "FLOOR": decimal.ROUND_FLOOR, "CEILING": decimal.ROUND_CEILING}


def test_decimal_matches_python(tmp_path):
    ctx = decimal.Context(prec=80, traps=[])
    rng = random.Random(99)

    def rand_dec():
        digits = rng.randint(1, 15)
        scale = rng.randint(0, 8)
        v = decimal.Decimal(rng.randint(-10 ** digits, 10 ** digits)).scaleb(-scale, ctx)
        return v

    lines = ["import std.decimal { decimal_parse, HALF_EVEN, HALF_UP, HALF_DOWN, UP, DOWN, FLOOR, CEILING }", "",
             "fn show(a_text: str, b_text: str, places: u32):",
             "    a = decimal_parse(a_text).value_or_panic()", "    b = decimal_parse(b_text).value_or_panic()",
             "    print(a.add(b).to_string(), a.sub(b).to_string(), a.mul(b).to_string(), a.compare(b))"]
    for m in MODES:
        lines.append(f"    print(a.round(places, {m}).to_string())")
        lines.append(f"    if not b.is_zero():")
        lines.append(f"        print(a.div(b, places, {m}).to_string())")
    lines += ["", "fn main():"]
    want = []
    for _ in range(40):
        a, b, places = rand_dec(), rand_dec(), rng.randint(0, 6)
        lines.append(f'    show("{a:f}", "{b:f}", {places})')
        want.append(f"{ctx.add(a, b):f} {ctx.subtract(a, b):f} {ctx.multiply(a, b):f} {(a > b) - (a < b)}")
        q = decimal.Decimal(1).scaleb(-places)
        for name, mode in MODES.items():
            want.append(f"{a.quantize(q, rounding=mode, context=ctx):f}")
            if b != 0:
                want.append(f"{_exact_div(a, b, q, mode):f}")
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    got = r.stdout.splitlines()
    assert len(got) == len(want)
    for g, w in zip(got, want):
        for gt, wt in zip(g.split(), w.split()):
            if decimal.Decimal(wt) == 0:
                wt = wt.lstrip("-")  # a negative number rounded to zero prints as -0.00 in Python
            assert gt == wt, (g, w)
        assert len(g.split()) == len(w.split())


def _exact_div(a, b, q, mode):
    # a / b to the places of `q` using exact rational arithmetic, rounded by `mode`
    ctx = decimal.Context(prec=200, rounding=mode, traps=[])
    return ctx.divide(a, b).quantize(q, rounding=mode, context=ctx)


def test_decimal_basics(tmp_path):
    r = run_gg_source(tmp_path, open(__file__.replace("test_std_decimal.py", "fixtures/decimal_program.gg"), encoding="utf-8").read())
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "59.97 4.95 64.92", "0.3 true", "2 4 3", "-3 -2 -3 3", "3.333333 -0.12", "1.5 1500 0.012 0.5",
        "true true 1.25", "-0.005 24691357802469135780.246913578", "0 7 2.5"]
