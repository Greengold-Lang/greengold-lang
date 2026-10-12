"""A block can be one simple statement after `:` on the same line (`if x: return 1`, `Leaf(v): return v`)."""
from tests.helpers import front_end, run_built

SRC = """\
enum Tree:
    Leaf(i32)
    Node(Box[Tree], Box[Tree])

fn sum(t: read Tree) -> i32:
    match t:
        Leaf(v): return v
        Node(a, b): return sum(a.value) + sum(b.value)

fn sign(x: i32) -> i32:
    if x > 0: return 1
    elif x < 0: return -1
    else: return 0

fn main():
    t = Tree.Node(Box[Tree](Tree.Leaf(1)), Box[Tree](Tree.Leaf(2)))
    print(sum(t), sign(-4), sign(0))
    total = 0
    for i in 0..5: total += i
    while total > 3: total -= 3
    print(total)
    match total:
        1: print("one")
        n if n > 1: print("more")
        _: pass
"""


def test_inline_blocks_run():
    assert run_built(SRC).stdout.splitlines() == ["3 -1 0", "1", "one"]


def test_a_block_statement_cannot_follow_the_colon():
    _p, diags = front_end("fn main():\n    x = 1\n    if x > 0: if x > 2: print(x)\n")
    assert [d.code for d in diags] == ["GG0118"]
    assert "opens a block" in diags[0].message


def test_a_broken_arm_is_not_reported_as_a_missing_arm():
    _p, diags = front_end("fn main():\n    match 1:\n        1 2:\n            pass\n")
    assert diags and all("at least one arm" not in d.message for d in diags)
