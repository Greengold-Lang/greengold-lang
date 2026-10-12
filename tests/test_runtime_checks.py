"""Execution modes, overflow, runtime checks."""
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from greengold.cli import compile_to_ir
from tests.helpers import run_built

ROOT = Path(__file__).resolve().parent.parent


def run_prog(src: str, release: bool = False, filename: str = "main.gg") -> subprocess.CompletedProcess[str]:
    return run_built(src, release=release, filename=filename)



def test_div_by_zero_panic():
    src = """
fn main():
    a = 10
    b = 0
    print(a / b)
"""
    res = run_prog(src, filename="div.gg")
    assert res.returncode == 101
    assert "Runtime error: division by zero" in res.stderr
    assert "--> div.gg:5:" in res.stderr


def test_mod_by_zero_panic():
    src = """
fn main():
    a = 10
    b = 0
    print(a % b)
"""
    res = run_prog(src, filename="mod.gg")
    assert res.returncode == 101
    assert "Runtime error: division by zero" in res.stderr
    assert "--> mod.gg:5:" in res.stderr


def test_int_div_overflow_panic():
    src = """
fn main():
    a: i32 = -2147483648
    b: i32 = -1
    print(a / b)
"""
    res = run_prog(src, filename="ovf.gg")
    assert res.returncode == 101
    assert "Runtime error: integer division overflow" in res.stderr
    assert "--> ovf.gg:5:" in res.stderr


def test_shift_count_panic():
    # >= bit width
    src1 = """
fn main():
    x: i32 = 1
    s: i32 = 32
    print(x << s)
"""
    res1 = run_prog(src1)
    assert res1.returncode == 101
    assert "Runtime error: shift amount out of bounds" in res1.stderr

    # negative shift count
    src2 = """
fn main():
    x: i32 = 1
    s: i32 = -1
    print(x >> s)
"""
    res2 = run_prog(src2)
    assert res2.returncode == 101
    assert "Runtime error: shift amount out of bounds" in res2.stderr


def test_float_div_by_zero_no_panic():
    src = """
fn main():
    a: f64 = 1.0
    b: f64 = 0.0
    print(a / b)
"""
    res = run_prog(src)
    assert res.returncode == 0
    # IEEE 754 inf
    assert "inf" in res.stdout.lower()


def test_inclusive_for_loop_max_bound():
    src = """
fn main():
    count = 0
    for i in u8(250)..=255:
        count += 1
    print(count)
"""
    res = run_prog(src)
    assert res.returncode == 0
    assert res.stdout.strip() == "6"


