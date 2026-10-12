"""Use-after-move through loops: a fixpoint over the loop head, with `break` and `continue` edges."""
import pytest

from .helpers import messages, run_built

TAKE = "fn take(xs: consume List[i32]):\n    print(xs.len)\n\n"


def check(body):
    return messages(TAKE + "fn main():\n    xs = List[i32]()\n" + "".join("    " + l + "\n" for l in body.splitlines()))


@pytest.mark.parametrize("body", [
    "for i in 0..3:\n    take(xs)\n    xs = List[i32]()",
    "while true:\n    take(xs)\n    break\nprint(1)",
    "for i in 0..3:\n    if i == 2:\n        take(xs)\n        return\n    print(xs.len)",
    "n = 0\nwhile n < 3:\n    n += 1\n    if n == 1:\n        print(xs.len)\n    else:\n        take(xs)\n        xs = List[i32]()",
])
def test_moves_that_never_reach_a_use_are_fine(body):
    assert check(body) == []


@pytest.mark.parametrize("body, text", [
    ("for i in 0..3:\n    take(xs)", "moved (`consume`) on each iteration"),
    ("while true:\n    take(xs)\n    break\nprint(xs.len)", "was moved"),
    ("for i in 0..3:\n    if i == 2:\n        take(xs)\n        continue\n    print(xs.len)", "on each iteration"),
])
def test_moves_that_reach_a_use_are_rejected(body, text):
    msgs = check(body)
    assert any(text in m for m in msgs), msgs


def test_move_and_reassign_in_loop_drops_each_value_once():
    src = ("struct Fd:\n    n: i32\n\nimpl Fd:\n    fn drop(self: lend Self):\n        print(self.n)\n\n"
           "fn take(f: consume Fd):\n    pass\n\n"
           "fn main():\n    f = Fd{ n: 0 }\n    for i in 1..3:\n        take(f)\n        f = Fd{ n: i }\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["0", "1", "2"]
