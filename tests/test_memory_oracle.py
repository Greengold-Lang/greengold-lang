"""The run-time memory oracle (tools/safety_oracle.py) has to see what it is built to see, and has to leave
correct programs alone. These build and run a few programs, so they take a few seconds each."""
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import safety_oracle as O  # noqa: E402

from .helpers import HAS_CC  # noqa: E402

pytestmark = pytest.mark.skipif(not HAS_CC, reason="needs a C compiler or zig to link")

# These programs are not memory safe on purpose (`unsafe:` turns the checks off), one per kind of damage.
READ_AFTER_FREE = """fn main():
    b = Box[i64](1234567)
    q: *i64 = null
    unsafe:
        pp = ptr_cast[**i64](addr(b))
        q = pp[0]
    b = Box[i64](7)
    unsafe:
        print(q[0])
"""
WRITE_AFTER_FREE = """fn main():
    b = Box[i64](1234567)
    q: *mut i64 = null
    unsafe:
        pp = ptr_cast[*mut *mut i64](addr(b))
        q = pp[0]
    b = Box[i64](7)
    unsafe:
        q[0] = 99
"""
DOUBLE_FREE = """fn main():
    b = Box[i64](5)
    unsafe:
        pp = ptr_cast[*mut *mut u8](addr(b))
        gg_oracle_free(pp[0])
"""


def test_a_read_through_a_dangling_pointer_changes_the_output(tmp_path):
    v = O.check_program(READ_AFTER_FREE, tmp_path)
    assert v.kind == "mismatch", v
    assert b"1234567" in v.stdout_leak and b"1234567" not in v.stdout_poison


def test_a_write_through_a_dangling_pointer_is_found_at_exit(tmp_path):
    v = O.check_program(WRITE_AFTER_FREE, tmp_path)
    assert v.kind == "write_after_free", v


def test_correct_programs_behave_the_same_and_leak_nothing(tmp_path):
    src = """struct P:
    name: string
    items: List[string]

fn main():
    xs = List[string]()
    for i in 0..20:
        xs.push(string.from("item") + i)
    p = P{ name: string.from("p"), items: xs.clone() }
    b = Box[P](p)
    arr = [string.from("a"), string.from("b")]
    print(xs.len, b.value.items.len, arr[1])
"""
    v = O.check_program(src, tmp_path)
    assert v.kind == "ok", v
    assert v.live == 0
    assert v.stdout_leak.split() == [b"20", b"20", b"b"]


def test_an_array_of_heap_values_is_freed_once(tmp_path):
    src = 'fn main():\n    a = string.from("x")\n    b = string.from("y")\n    arr = [b, a]\n    print(arr[0], arr[1])\n'
    v = O.check_program(src, tmp_path)
    assert v.kind == "ok", v


def test_freeing_a_block_that_the_program_still_owns_is_a_double_free(tmp_path):
    v = O.check_program(DOUBLE_FREE, tmp_path)
    assert v.kind == "double_free", v
