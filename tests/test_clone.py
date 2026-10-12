"""`x.clone()`: deep copy of heap-owning values (no leaks, no shared buffers)."""
import os

from tests.helpers import messages, run_built

PROGRAM = """\
struct Inv:
    name: string
    items: List[i32]

enum Tree:
    Leaf(i32)
    Node(Box[Tree], Box[Tree])

fn sum(t: Tree) -> i32:
    return match t:
        Leaf(v) => v
        Node(a, b) => sum(a.value) + sum(b.value)

fn main():
    v = List[i32]()
    v.push(1)
    w = v.clone()
    w.push(2)
    print(v.len, w.len)
    a = Inv{ name: string.from("bag"), items: v.clone() }
    c = a.clone()
    c.items.push(9)
    c.name.append_str("!")
    print(a.items.len, c.items.len, a.name, c.name)
    t = Tree.Node(Box[Tree](Tree.Leaf(1)), Box[Tree](Tree.Leaf(2)))
    u = t.clone()
    print(sum(t), sum(u))
    g = List[List[i32]]()
    g.push(v.clone())
    h = g.clone()
    n = 3
    print(h.len, n.clone())
"""


def test_clone_is_deep_and_leak_free(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["1 2", "1 2 bag bag!", "3 3", "1 3"]
    assert "leak" not in r.stderr.lower()


def test_user_defined_clone_wins():
    src = """\
struct S:
    xs: List[i32]

impl S:
    fn clone(self: Self) -> i32:
        return 7

fn main():
    s = S{ xs: List[i32]() }
    print(s.clone())
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "7"


def test_clone_rejects_lend_reference_fields():
    src = """\
struct P:
    hp: i32

struct Slot:
    who: lend P tied to self

fn main():
    p = P{ hp: 1 }
    s = Slot{ who: p }
    t = s.clone()
"""
    assert any("cannot be cloned" in m for m in messages(src))


def test_printing_a_string_field_does_not_free_it(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
struct Inv:
    name: string
    n: i32

fn main():
    a = Inv{ name: string.from("bag"), n: 1 }
    print(a.n)
    print(a.name)
    print(f"[{a.name}]")
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["1", "bag", "[bag]"]
