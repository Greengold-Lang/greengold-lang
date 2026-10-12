"""if / match as expression: `if c then a else b`, `match x:` + `Arm => value`."""
import pytest

from .helpers import HAS_CC, messages
from .test_heap import ok

needs_cc = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

SHAPES = """
enum Shape:
    Circle(i32)
    Rect(i32, i32)
    Empty
"""


@needs_cc
def test_if_expression(tmp_path):
    src = """
fn sign(n: i32) -> i32:
    return if n < 0 then -1 elif n == 0 then 0 else 1

fn main():
    a = if sign(5) > 0 then 10 else 20
    print(a)
    print(sign(-9))
    print(sign(0))
    big = if a > 5 then i64(7) else i64(8)
    print(big)
    print(1 + if a == 10 then 100 else 200)
"""
    ok(tmp_path, src, ["10", "-1", "0", "7", "101"])


@needs_cc
def test_match_expression(tmp_path):
    src = SHAPES + """
fn area(s: Shape) -> i32:
    return match s:
        Circle(r) => 3 * r * r
        Rect(w, h) => w * h
        Empty => 0

fn main():
    print(area(Shape.Circle(2)))
    print(area(Shape.Rect(3, 4)))
    k = match Shape.Empty:
        Circle(_) => 1
        _ => 2
    print(k)
    print(area(Shape.Rect(2, 2)) + 1)
"""
    ok(tmp_path, src, ["12", "12", "2", "5"])


@needs_cc
def test_match_expression_heap_result_no_leak(tmp_path):
    src = """
enum Pick:
    Left
    Right

fn make(p: Pick) -> List[i32]:
    a = List[i32]()
    a.push(1)
    b = List[i32]()
    b.push(2)
    b.push(3)
    return match p:
        Left => a
        Right => b

fn main():
    x = make(Pick.Right)
    y = make(Pick.Left)
    print(x.len)
    print(y.len)
    z = if x.len > 1 then List[i32]() else List[i32]()
    print(z.len)
"""
    ok(tmp_path, src, ["2", "1", "0"])


def test_branch_types_must_match():
    errs = messages("fn main():\n    x = if true then 1 else false\n    print(x)\n")
    assert errs
    errs = messages(SHAPES + "fn main():\n    x = match Shape.Empty:\n        Circle(_) => 1\n        Rect(_, _) => 2\n")
    assert any("cover all cases" in m for m in errs)



def test_if_expression_needs_else_and_then():
    assert messages("fn main():\n    x = if true then 1\n    print(x)\n")
    assert messages("fn main():\n    x = if true: 1 else 2\n    print(x)\n")


def test_moved_in_one_arm_is_moved_after():
    src = SHAPES.replace("Empty", "Empty") + """
fn main():
    v = List[i32]()
    n = if true then 1 else 2
    w = if n > 1 then v else List[i32]()
    print(v.len)
    print(w.len)
"""
    assert any("can no longer be used" in m for m in messages(src))
