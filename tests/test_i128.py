"""128-bit integers: i128 and u128."""
from tests.helpers import run_gg_source

PROGRAM = open(__file__.replace("test_i128.py", "fixtures/i128_program.gg"), encoding="utf-8").read()


def test_128_bit_integers(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "340282366920938463463374607431768211455 -170141183460469231731687303715884105728 12345678901234567890123",
        "12345678901234567890123007 4115226300411522630041002 7 12333333222333333322232884 7",
        "true true true",
        "340282366920938463426481119284349108225",
        "12345678901234567890123 and 340282366920938463463374607431768211455",
        "12345678901234567890124 true 0",
        "170141183460469231731687303715884105727 0 170141183460469231731687303715884105727",
        "6338253001141147007483516026880 2 -5",
    ]


def test_128_bit_overflow_traps(tmp_path):
    r = run_gg_source(tmp_path, "fn main():\n    a: u128 = 340282366920938463463374607431768211455\n    b = a + 1\n    print(b)\n")
    assert r.returncode != 0
    assert "overflow" in r.stderr
