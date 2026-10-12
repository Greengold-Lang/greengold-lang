"""Numeric types, conversions, bitwise operations."""
from pathlib import Path
import subprocess
import sys
import pytest

from greengold.cli import compile_to_ir
from tests.helpers import run_built
from greengold.diagnostics import CompileError
from greengold.lexer import tokenize, DiagnosticBag
from greengold.parser import parse
from greengold.typecheck import check_program

ROOT = Path(__file__).resolve().parent.parent


def run_prog(src: str) -> list[str]:
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    return res.stdout.splitlines()



def must_fail(src: str, text: str):
    with pytest.raises(CompileError) as exc_info:
        compile_to_ir(src)
    msgs = [d.message for d in exc_info.value.diagnostics]
    assert any(text in m for m in msgs), f"Expected `{text}` not in error messages: {msgs}"


def test_lexer_literals():
    diags = DiagnosticBag()
    toks = tokenize("0xFF 0b1010 1_000_000 0x1A_2B", diags)
    assert not diags.has_errors()
    assert [t.text for t in toks if t.kind == "INT"] == ["255", "10", "1000000", "6699"]


def test_parser_no_chained_comparisons():
    src = "fn main():\n    x = 1 < 2 < 3\n"
    must_fail(src, "Chained comparison operations are not supported.")


def test_integer_ranges():
    must_fail("fn main():\n    x: u8 = 256\n", "256 is too large for `u8`.")
    must_fail("fn main():\n    x: u32 = -1\n", "Unary `-` cannot be used with unsigned type (`u32`).")
    must_fail("fn main():\n    x: i8 = 128\n", "128 is too large for `i8`.")
    must_fail("fn main():\n    x: i8 = -129\n", "-129 is too small for `i8`.")


def test_cast_const_range():
    must_fail("fn main():\n    x = u8(300)\n", "Constant value 300 is out of range [0, 255] for `u8`.")
    must_fail("fn main():\n    x = u8(-1)\n", "Constant value -1 is out of range [0, 255] for `u8`.")
    must_fail("fn main():\n    x = i32(true)\n", "Type `bool` cannot be converted to type `i32`.")


def test_bitwise_typing():
    must_fail("fn main():\n    x = 1.5 & 2.5\n", "`&` can only be used with integers")
    must_fail("fn main():\n    x: u32 = 1\n    y: i32 = 2\n    z = x & y\n", "must have the same type")
    must_fail("fn main():\n    x = ~1.5\n", "`~` can only be used with integers")
    must_fail("fn main():\n    x = 1 << 2.5\n", "`<<` right operand (shift amount) must be an integer")


def test_small_int_overflow_traps_and_wrapping_wraps():
    src = """
fn main():
    a: u8 = 200
    b: u8 = 100
    print(wrapping_add[u8](a, b))
    c = a + b
    print(c)
"""
    res = run_built(src)
    assert res.stdout.splitlines() == ["44"]
    assert res.returncode == 101 and "integer overflow" in res.stderr


def test_cast_runtime_and_print_types():
    src = """
fn main():
    x: i32 = 300
    y = u8(x)
    print(y)

    c1: i8 = -10
    c2: i16 = -200
    c3: i32 = -3000
    c4: i64 = -40000
    c5: isize = -50000
    u1: u8 = 10
    u2: u16 = 200
    u3: u32 = 3000
    u4: u64 = 40000
    u5: usize = 50000
    print(c1, c2, c3, c4, c5)
    print(u1, u2, u3, u4, u5)
"""
    out = run_prog(src)
    assert out[0] == "44"
    assert out[1] == "-10 -200 -3000 -40000 -50000"
    assert out[2] == "10 200 3000 40000 50000"


def test_bitwise_operations_and_precedence():
    src = """
fn main():
    a: u32 = 0b1100
    b: u32 = 0b1010
    print(a & b)
    print(a | b)
    print(a ^ b)
    print(a << 2)
    print(a >> 1)
    
    # Precedence: | < ^ < &
    # 1 | 2 ^ 3 & 3 == 1 | (2 ^ (3 & 3)) == 1 | (2 ^ 3) == 1 | 1 == 1
    print(1 | 2 ^ 3 & 3)

    # Shift count can be different int type
    shift: u8 = 3
    val: u64 = 1
    print(val << shift)

    # Compound assignments
    m: u32 = 0b1111
    m &= 0b0101
    m |= 0b0010
    m ^= 0b0001
    m <<= 1
    m >>= 1
    print(m)
"""
    out = run_prog(src)
    assert out == [
        "8",    # 1100 & 1010 = 1000 = 8
        "14",   # 1100 | 1010 = 1110 = 14
        "6",    # 1100 ^ 1010 = 0110 = 6
        "48",   # 12 << 2 = 48
        "6",    # 12 >> 1 = 6
        "1",    # 1 | 2 ^ 3 & 3 = 1
        "8",    # 1 << 3 = 8
        "6",    # ((0b1111 & 0b0101) | 0b0010) ^ 0b0001 = (5 | 2) ^ 1 = 7 ^ 1 = 6
    ]


def test_signed_left_shift_no_ub():
    src = """
fn main():
    s: i32 = -1
    print(s << 1)
    s8: i8 = -1
    print(s8 << 1)
"""
    assert run_prog(src) == ["-2", "-2"]
