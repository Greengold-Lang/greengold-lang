from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from .helpers import messages


def error_of(src: str) -> str:
    msgs = messages(src)
    assert msgs, "error expected but not found"
    return " ".join(msgs)


def run_source(tmp_path: Path, src: str, release: bool = False) -> subprocess.CompletedProcess[str]:
    re_file = tmp_path / "main.gg"
    re_file.write_text(src, encoding="utf-8")
    cmd = ["python", "-m", "greengold", "run", str(re_file)]
    if release:
        cmd.append("--release")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


gcc_available = shutil.which("gcc") is not None or shutil.which("clang") is not None


# --- Compile-time error tests ---

def test_const_index_out_of_bounds():
    src = """fn main():
    a = [1, 2, 3]
    print(a[5])
"""
    err = error_of(src)
    assert "Constant index 5 out of bounds" in err


def test_const_index_negative():
    src = """fn main():
    a = [1, 2, 3]
    print(a[-1])
"""
    err = error_of(src)
    assert "Constant index -1 out of bounds" in err


def test_assign_to_read_slice_element():
    src = """fn modify(s: []i32):
    s[0] = 42

fn main():
    return
"""
    err = error_of(src)
    assert "is a read-only slice" in err


def test_slice_local_variable_storage():
    src = """fn main():
    a = [1, 2, 3, 4]
    s = a[1..3]
    print(s)
"""
    assert messages(src) == []


def test_slice_in_struct_field():
    src = """struct View:
    data: []i32

fn main():
    a = [1, 2]
    v = View{ data: a[0..1] }
    print(v.data)
"""
    assert messages(src) == []


def test_slice_as_return_type():
    src = """fn get_slice(xs: read List[i32]) -> []i32:
    return xs[0..0]

fn main():
    xs = List[i32]()
    print(get_slice(xs))
"""
    assert messages(src) == []


def test_give_primitive_array():
    src = """fn take(a: consume [3]i32):
    return

fn main():
    nums = [1, 2, 3]
    take(nums)
"""
    err = error_of(src)
    assert "is copied, `consume` is not needed" in err


def test_give_array_element():
    src = """struct Item:
    id: i32

fn take(item: consume Item):
    return

fn main():
    items = [Item{ id: 1 }, Item{ id: 2 }]
    take(items[0])
"""
    err = error_of(src)
    assert "`items[0]` cannot be moved out" in err


def test_pass_read_slice_to_lend_slice():
    src = """fn modify(s: lend []i32):
    s[0] = 10

fn inspect(s: []i32):
    modify(s)

fn main():
    return
"""
    err = error_of(src)
    assert "is a read-only slice" in err


def test_lend_immutable_array_to_lend_slice():
    src = """fn modify(s: lend []i32):
    s[0] = 10

fn main():
    fixed nums = [1, 2, 3]
    modify(nums)
"""
    err = error_of(src)
    assert "`nums` cannot be `lend`ed: `nums` is declared `fixed`" in err



# --- Runtime execution & panic tests ---

@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_acceptance_arrays(tmp_path: Path):
    src = """fn sum(a: []i32) -> i32:
    total = 0
    for x in a:
        total += x
    return total

fn sort(a: lend []i32):
    i: usize = 0
    while i < a.len:
        j: usize = 0
        while j + 1 < a.len - i:
            if a[j] > a[j + 1]:
                t = a[j]
                a[j] = a[j + 1]
                a[j + 1] = t
            j += 1
        i += 1

fn main():
    nums = [5, 2, 9, 1, 7]
    print(sum(nums))
    sort(nums)
    for i in 0..nums.len:
        print(nums[i])
    print(sum(nums[1..4]))
"""
    res = run_source(tmp_path, src)
    assert res.returncode == 0
    assert res.stdout.strip().splitlines() == ["24", "1", "2", "5", "7", "9", "14"]


@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_bounds_panic_index(tmp_path: Path):
    src = """fn main():
    a = [10, 20, 30]
    i = 5
    print(a[i])
"""
    res = run_source(tmp_path, src)
    assert res.returncode == 101
    assert "Runtime error: array index out of bounds (index 5, length 3)" in res.stderr


@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_bounds_panic_slice(tmp_path: Path):
    src = """fn take(s: []i32):
    print(s.len)

fn main():
    a = [1, 2, 3, 4]
    hi = 10
    take(a[1..hi])
"""
    res = run_source(tmp_path, src)
    assert res.returncode == 101
    assert "Runtime error: slice range out of bounds (range 1..10, length 4)" in res.stderr


@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_array_repeat_literal(tmp_path: Path):
    src = """fn main():
    a = [42; 4]
    for x in a:
        print(x)
    print(a.len)
"""
    res = run_source(tmp_path, src)
    assert res.returncode == 0
    assert res.stdout.strip().splitlines() == ["42", "42", "42", "42", "4"]


@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_multidimensional_array(tmp_path: Path):
    src = """fn main():
    grid = [[1, 2], [3, 4]]
    grid[0][1] = 9
    print(grid[0][0])
    print(grid[0][1])
    print(grid[1][0])
    print(grid[1][1])
"""
    res = run_source(tmp_path, src)
    assert res.returncode == 0
    assert res.stdout.strip().splitlines() == ["1", "9", "3", "4"]


@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_slice_inclusive(tmp_path: Path):
    src = """fn sum(s: []i32) -> i32:
    total = 0
    for x in s:
        total += x
    return total

fn main():
    nums = [10, 20, 30, 40, 50]
    print(sum(nums[1..=3]))
"""
    res = run_source(tmp_path, src)
    assert res.returncode == 0
    # nums[1..=3] is indices 1, 2, 3 -> 20 + 30 + 40 = 90
    assert res.stdout.strip().splitlines() == ["90"]


@pytest.mark.skipif(not gcc_available, reason="gcc or clang not found")
def test_release_mode_bounds_skipped(tmp_path: Path):
    src = """fn main():
    a = [1, 2, 3]
    i = 1
    print(a[i])
"""
    res = run_source(tmp_path, src, release=True)
    assert res.returncode == 0
    assert res.stdout.strip() == "2"

