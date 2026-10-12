"""`allocator alloc, resize, free`: a program's heap goes through its own functions."""
from pathlib import Path

import pytest

from .helpers import messages, run_built

COUNTING = """extern "stdlib.h" fn malloc(size: usize) -> *mut u8
extern "stdlib.h" fn realloc(p: *mut u8, size: usize) -> *mut u8
extern "stdlib.h" fn free(p: *mut u8)

static ALLOCS: i64 = 0
static FREES: i64 = 0

fn counting_alloc(size: usize) -> *mut u8:
    unsafe:
        ALLOCS += 1
        return malloc(size)

fn counting_resize(p: *mut u8, size: usize) -> *mut u8:
    unsafe:
        if p == null:
            ALLOCS += 1
        return realloc(p, size)

fn counting_free(p: *mut u8):
    unsafe:
        FREES += 1
        free(p)

allocator counting_alloc, counting_resize, counting_free

fn work():
    xs = List[i32]()
    for i in 0..100:
        xs.push(i)
    b = Box[i64](5)
    s = string.from("hello")
    print(xs.len, b.value, s)

fn main():
    work()
    unsafe:
        print(ALLOCS, FREES)
"""


def test_every_heap_allocation_goes_through_the_allocator():
    res = run_built(COUNTING)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["100 5 hello", "3 3"]


@pytest.mark.parametrize("line, text", [
    ("allocator a, b, missing", "no Greengold function named `missing`"),
    ("allocator b, b, c", "must be `fn b(size: usize) -> *mut u8`"),
])
def test_allocator_errors(line, text):
    src = ("fn a(size: usize) -> *mut u8:\n    return null\n\nfn b(p: *mut u8, size: usize) -> *mut u8:\n    return p\n\n"
           "fn c(p: *mut u8):\n    pass\n\n" + line + "\n\nfn main():\n    pass\n")
    msgs = messages(src)
    assert any(text in m for m in msgs), msgs


def test_no_std_heap_with_a_bump_allocator(tmp_path: Path):
    from greengold.cli import main
    src = tmp_path / "bare.gg"
    src.write_text("""static HEAP: [4096]u8 = [0; 4096]
static TOP: usize = 0

fn bump_alloc(size: usize) -> *mut u8:
    unsafe:
        at = (TOP + 15) / 16 * 16
        if at + size > 4096:
            return null
        TOP = at + size
        return ptr_offset(ptr_cast[*mut u8](addr_mut(HEAP)), isize(at))

fn bump_resize(p: *mut u8, size: usize) -> *mut u8:
    return bump_alloc(size)

fn bump_free(p: *mut u8):
    pass

allocator bump_alloc, bump_resize, bump_free

fn main():
    xs = List[i32]()
    xs.push(1)
""", encoding="utf-8")
    out = tmp_path / "bare.ll"
    assert main(["emit-ll", "--no-std", str(src), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "@malloc" not in text and "@free" not in text
