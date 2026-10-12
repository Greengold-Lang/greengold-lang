"""Slices as variables, fields, and results: views that follow the borrow rules of `str`."""
import pytest

from .helpers import messages, run_built


def test_slices_stored_returned_and_in_structs():
    src = """struct Window:
    rows: []i32

fn head(xs: read List[i32]) -> []i32:
    return xs[0..2]

fn sum(xs: []i32) -> i32:
    t = 0
    for x in xs:
        t += x
    return t

fn main():
    xs = List[i32]()
    for i in 0..5:
        xs.push(i * 10)
    h = head(xs)
    print(h, h.len, sum(h))
    w = Window{ rows: xs[1..4] }
    print(w.rows, w.rows[0])
    arr: [4]i32 = [1, 2, 3, 4]
    part = arr[2..]
    print(sum(part))
"""
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["[0, 10] 2 10", "[10, 20, 30] 10", "7"]


@pytest.mark.parametrize("src, text", [
    ("fn bad() -> []i32:\n    arr: [3]i32 = [1, 2, 3]\n    return arr[0..2]\n\nfn main():\n    pass\n", "destroyed upon returning"),
    ("fn main():\n    xs = List[i32]()\n    s = xs[0..0]\n    xs.push(2)\n    print(s)\n", "still tied to it"),
    ("fn main():\n    xs = List[i32]()\n    xs.push(1)\n    s = xs[0..1]\n    s[0] = 5\n", "read-only view"),
    ("fn mk() -> List[i32]:\n    return List[i32]()\n\nfn main():\n    s = mk()[0..0]\n    print(s)\n", "temporary value"),
    ("fn pick(a: read List[i32], b: read List[i32]) -> []i32:\n    return b[0..0]\n\n"
     "fn main():\n    a = List[i32]()\n    b = List[i32]()\n    s = pick(a, b)\n    b.push(1)\n    print(s)\n", "still tied"),
])
def test_slice_views_are_checked(src, text):
    msgs = messages(src)
    assert any(text in m for m in msgs), msgs


def test_dead_slice_releases_its_owner():
    assert messages("fn main():\n    xs = List[i32]()\n    s = xs[0..0]\n    print(s)\n    xs.push(2)\n") == []
