"""Calling C functions (extern)."""
from pathlib import Path
import subprocess
import sys
import pytest

from greengold.cli import compile_to_ir
from tests.helpers import run_built
from greengold.diagnostics import CompileError

ROOT = Path(__file__).resolve().parent.parent


def run_prog(src: str, extra_c: str = "") -> subprocess.CompletedProcess[str]:
    return run_built(src, extra_c=extra_c)



def must_fail(src: str, text: str):
    with pytest.raises(CompileError) as exc_info:
        compile_to_ir(src)
    msgs = [d.message for d in exc_info.value.diagnostics]
    assert any(text in m for m in msgs), f"Expected `{text}` not in error messages: {msgs}"



def test_extern_math_acceptance():
    src = (ROOT / "examples" / "extern_math.gg").read_text(encoding="utf-8")
    res = run_prog(src)
    assert res.returncode == 0
    assert res.stdout.strip() == "1.4142135623731"


def test_extern_math_header_includes_and_no_prototype():
    src = """
extern "math.h" fn sqrt(x: f64) -> f64

fn main():
    print(sqrt(4.0))
"""
    res = run_prog(src)
    assert res.returncode == 0
    assert res.stdout.strip() == "2"


def test_extern_without_header_generates_prototype():
    src = """
extern fn custom_add(a: i32, b: i32) -> i32

fn main():
    print(custom_add(15, 27))
"""
    assert 'declare i32 @"custom_add"(i32' in compile_to_ir(src)
    extra_c = """
#include <stdint.h>
int32_t custom_add(int32_t a, int32_t b) {
    return a + b;
}
"""
    res = run_prog(src, extra_c=extra_c)
    assert res.returncode == 0
    assert res.stdout.strip() == "42"


def test_extern_string_parameter_passes_char_pointer():
    src = """
extern "stdio.h" fn puts(s: str) -> i32

fn main():
    msg = "Hello from extern"
    puts(msg)
    puts("Direct literal")
"""
    assert 'declare i32 @"puts"(i8*' in compile_to_ir(src)
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == ["Hello from extern", "Direct literal"]


def test_extern_lend_parameter():
    src = """
extern fn increment(val: lend i32)

fn main():
    x = 10
    increment(x)
    print(x)
"""
    assert 'declare void @"increment"(i32*' in compile_to_ir(src)
    extra_c = """
#include <stdint.h>
void increment(int32_t *val) {
    (*val) += 5;
}
"""
    res = run_prog(src, extra_c=extra_c)
    assert res.returncode == 0
    assert res.stdout.strip() == "15"


def test_extern_errors_slice_param():
    must_fail("extern fn f(s: []i32)\n", "cannot use slice parameter in extern functions")


def test_extern_errors_array_param():
    must_fail("extern fn f(a: [5]i32)\n", "cannot use array parameter in extern functions")


def test_extern_variadic_requires_unsafe():
    # variadic extern is supported (see tests/test_ffi.py) but only callable inside unsafe
    must_fail('extern fn printf(fmt: string, ...)\n\nfn main():\n    printf("x")\n', "unsafe")


def test_extern_variadic_needs_fixed_param():
    must_fail("extern fn f(...)\n", "requires at least one fixed parameter")


def test_extern_errors_string_return():
    must_fail("extern fn get_str() -> string\n", "extern functions cannot return `string`")


def test_extern_errors_give_param():
    src = """
struct Player:
    health: i32
extern fn take(p: consume Player)
"""
    must_fail(src, "cannot use `consume` parameter in extern functions")


def test_extern_errors_body_not_allowed():
    must_fail("extern fn f():\n    return\n", "cannot have a body")


def test_extern_duplicate_with_regular_fn():
    src1 = """
extern fn foo(a: i32) -> i32

fn foo(a: i32) -> i32:
    return a
"""
    must_fail(src1, "Cannot define both a normal Greengold function and an extern function")

    src2 = """
fn foo(a: i32) -> i32:
    return a

extern fn foo(a: i32) -> i32
"""
    must_fail(src2, "Cannot define both a normal Greengold function and an extern function")

