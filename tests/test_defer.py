"""`defer`: deferred statements running in reverse order on scope exit."""
import pytest

from .helpers import HAS_CC, messages
from .test_heap import ok

needs_cc = pytest.mark.skipif(not HAS_CC, reason="no C compiler")


@needs_cc
def test_defer_order_and_early_exits(tmp_path):
    src = """
fn bye(n: i32):
    print(n)

fn work(n: i32) -> i32:
    defer bye(100)
    defer bye(200)
    if n > 0:
        defer bye(300)
        return n
    print(1)
    return 0

fn main():
    print(work(5))
    print(work(0))
    for i in 0..4:
        defer bye(i + 10)
        if i == 1:
            continue
        if i == 2:
            break
        print(i)
    print(99)
"""
    # work(5): 300, 200, 100, then 5; work(0): 1, 200, 100, then 0; loop: 0, 10, 11, 12; 99
    ok(tmp_path, src, ["300", "200", "100", "5", "1", "200", "100", "0", "0", "10", "11", "12", "99"])


@needs_cc
def test_defer_with_heap_no_leak(tmp_path):
    src = """
fn note(v: read List[i32]):
    print(v.len)

fn main():
    v = List[i32]()
    defer note(v)
    v.push(1)
    v.push(2)
    print(7)
"""
    ok(tmp_path, src, ["7", "2"])


def test_defer_restrictions():
    assert messages("fn f() -> Result[i32, i32]:\n    defer f()?\n    return Ok(1)\n\nfn main():\n    pass\n")
    assert messages("fn main():\n    defer 5\n")
