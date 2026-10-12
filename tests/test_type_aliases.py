"""Tests for primitive type aliases: int (i32), uint (u32), float (f32), double (f64)."""
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import HAS_CC, ROOT, messages, run_gg_source


def test_type_alias_vars_and_casts_typecheck():
    msgs = messages("""
struct Vec2:
    x: float
    y: float

fn add(a: int, b: int) -> int:
    return a + b

fn dot(v: Vec2, w: Vec2) -> double:
    return double(v.x * w.x + v.y * w.y)

fn main():
    x: int = 10
    y: uint = 20
    z: float = 3.5
    w: double = 4.25
    v1 = Vec2{x: z, y: float(x)}
    v2 = Vec2{x: float(y), y: 1.0}
    d: double = dot(v1, v2)
    sum: int = add(x, int(z))
""")
    assert not msgs, msgs


def test_type_alias_execution_llvm(tmp_path: Path):
    r = run_gg_source(tmp_path, """
struct Point:
    x: float
    y: float

fn add(a: int, b: int) -> int:
    return a + b

fn main():
    a: int = 15
    b: uint = 25
    f: float = 2.5
    d: double = 10.75
    p = Point{x: f, y: float(a)}
    res: int = add(a, int(p.y))
    print(res)
    print(uint(res) + b)
    print(int(d))
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["30", "55", "10"]


def test_type_alias_generics_and_composite(tmp_path: Path):
    r = run_gg_source(tmp_path, """
type Score = int

fn sum_slice(s: []int) -> int:
    total: int = 0
    for x in s:
        total += x
    return total

fn main():
    arr: [3]int = [10, 20, 30]
    sc: Score = sum_slice(arr[0..3])
    print(sc)
    list = List[int]()
    list.push(sc)
    list.push(int(5.5))
    print(list.len)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["60", "2"]


def test_type_alias_reserved_names():
    # struct int
    msgs = messages("""
struct int:
    x: bool
fn main():
    pass
""")
    assert any("`int` is a reserved name" in m for m in msgs)

    # fn float
    msgs = messages("""
fn float():
    pass
fn main():
    pass
""")
    assert any("`float` is a reserved name" in m for m in msgs)

    # const double
    msgs = messages("""
const double: int = 1
fn main():
    pass
""")
    assert any("`double` is a reserved name" in m for m in msgs)

    # type int = i64
    msgs = messages("""
type int = i64
fn main():
    pass
""")
    assert any("Type alias `int` is already defined" in m for m in msgs)
