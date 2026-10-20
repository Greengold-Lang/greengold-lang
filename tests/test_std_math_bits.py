"""std.math (libm, generic helpers) and std.bits."""
from tests.helpers import run_gg_source


def _out(tmp_path, src):
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_math_libm_and_generics(tmp_path):
    out = _out(tmp_path, """import std.math

fn main():
    print(math.log10(1000.0), math.log2(8.0), math.round(2.5), math.trunc(-2.7), math.hypot(3.0, 4.0))
    print(math.is_nan(0.0 / 0.0), math.is_inf(1.0 / 0.0), math.is_finite(1.0), math.is_inf(1.0))
    print(math.min(3, 2), math.max(2.5, 1.0), math.clamp(15, 0, 10), math.abs(-4), math.signum(-9))
    print(math.isqrt(99), math.isqrt(max_value[u64]()), math.lcm_u64(4, 6), math.rem_euclid(-7, 3))
    print(math.checked_pow_i64(10, 30).is_none(), math.saturating_pow_i64(10, 30))
""")
    assert out[0] == "3 3 3 -2 5"
    assert out[1] == "true true true false"
    assert out[2] == "2 2.5 10 4 -1"
    assert out[3] == "9 4294967295 12 2"
    assert out[4] == "true 9223372036854775807"


def test_bits(tmp_path):
    out = _out(tmp_path, """import std.bits

fn main():
    print(bits.popcount(u8(255)), bits.popcount(i32(-1)), bits.leading_zeros(u32(1)), bits.trailing_zeros(u8(0)))
    print(bits.rotate_left(u8(129), 1), bits.rotate_right(u32(1), 1), bits.rotate_left(i8(-128), 1))
    print(bits.swap_bytes(u32(0x11223344)), bits.reverse_bits(u8(1)), bits.ilog2(1024))
    print(bits.next_power_of_two(u32(33)), bits.is_power_of_two(64), bits.is_power_of_two(0))
    print(bits.bits_extract(u32(0xABCD), 4, 8), bits.bits_insert(u32(0), 8, 4, 0xF), bits.bit_set(u8(0), 7))
""")
    assert out == ["8 32 31 8", "3 2147483648 1", "1144201745 128 10", "64 true false", "188 3840 128"]


def test_generic_call_with_cast_literal_infers_cast_type(tmp_path):
    out = _out(tmp_path, "fn id[T: Int](x: T) -> T:\n    return x\n\nfn main():\n    print(id(u64(7)), id(u8(1) << 3))\n")
    assert out == ["7 8"]
