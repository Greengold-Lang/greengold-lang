"""std.bigint against Python's integers."""
import math
import random

from tests.helpers import run_gg_source


def test_bigint_random_operations_match_python(tmp_path):
    rng = random.Random(12345)

    def rand_int():
        bits = rng.choice([1, 8, 31, 32, 33, 64, 65, 100, 200, 500, 1000])
        v = rng.getrandbits(bits)
        if rng.random() < 0.2:
            v = (1 << bits) - rng.randint(0, 3)  # carries and borrows across limbs
        return -v if rng.random() < 0.4 else v

    pairs = [(rand_int(), rand_int()) for _ in range(60)]
    pairs += [(1 << 128, (1 << 64) + 1), ((1 << 96) - 1, (1 << 32) - 1), (10 ** 40, 10 ** 20), (0, 5)]
    lines = ["import std.bigint { bigint_parse }", "", "fn show(a_text: str, b_text: str):",
             "    a = bigint_parse(a_text).value_or_panic()", "    b = bigint_parse(b_text).value_or_panic()",
             "    print(a.add(b).to_string(), a.sub(b).to_string(), a.mul(b).to_string())",
             "    if b.is_zero():", "        return",
             "    qr = a.div_rem(b)", "    print(qr.f0.to_string(), qr.f1.to_string(), a.modulo(b).to_string(), a.gcd(b).to_string())",
             "", "fn main():"]
    want = []
    for a, b in pairs:
        lines.append(f'    show("{a}", "{b}")')
        want.append(f"{a + b} {a - b} {a * b}")
        if b != 0:
            q = abs(a) // abs(b)
            q = -q if (a < 0) != (b < 0) else q
            want.append(f"{q} {a - q * b} {a % abs(b)} {math.gcd(a, b)}")
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_bigint_powers_hex_and_modular(tmp_path):
    r = run_gg_source(tmp_path, """import std.bigint { bigint_from_i64, bigint_parse }

fn main():
    print(bigint_from_i64(2).pow(200).to_string())
    print(bigint_from_i64(2).pow(130).to_hex(), bigint_parse("0xFFFFFFFFFFFFFFFFFFFF").value_or_panic().to_string())
    m = bigint_parse("1000000007").value_or_panic()
    print(bigint_from_i64(3).pow_mod(bigint_from_i64(1000), m).to_string(), bigint_from_i64(3).mod_inverse(m).value_or_panic().to_string())
    big = bigint_parse("-9223372036854775808").value_or_panic()
    print(big.to_i64().value_or(0), bigint_parse("12x").is_err(), bigint_from_i64(6).mod_inverse(bigint_from_i64(9)).is_none())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [str(2 ** 200), f"{hex(2 ** 130)} {0xFFFFFFFFFFFFFFFFFFFF}",
                                     f"{pow(3, 1000, 1000000007)} {pow(3, -1, 1000000007)}", "-9223372036854775808 true true"]
