"""Stage C: Box/List, ownership, automatic drop. Running programs with GG_LEAKCHECK=1 must have no leaks."""
import os
import subprocess
import sys

import pytest

from .helpers import HAS_CC, ROOT, messages, EXAMPLES_DIR

needs_cc = pytest.mark.skipif(not HAS_CC, reason="No C compiler")


def run(tmp_path, src, release=False):
    f = tmp_path / "h.gg"
    f.write_text(src, encoding="utf-8")
    cmd = [sys.executable, "-m", "greengold", "run", str(f)] + (["--release"] if release else [])
    env = dict(os.environ, GG_LEAKCHECK="1")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=120)


def ok(tmp_path, src, expected):
    for rel in (False, True):
        r = run(tmp_path, src, release=rel)
        assert r.returncode == 0, r.stderr
        assert "LEAK" not in r.stderr, r.stderr

        assert r.stdout.split() == expected, r.stdout


@needs_cc
def test_example_list_and_vec(tmp_path):
    r = subprocess.run([sys.executable, "-m", "greengold", "run", str(EXAMPLES_DIR / "heap_list.gg")],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                       env=dict(os.environ, GG_LEAKCHECK="1"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["10", "10", "9", "285", "81"]
    assert "SIZINTI" not in r.stderr


@needs_cc
def test_early_return_break_continue_drop(tmp_path):
    src = """
fn find(n: i32) -> i32:
    v = List[i32]()
    for i in 0..10:
        v.push(i)
    b = Box[i32](7)
    if n > 3:
        return i32(v.len)
    return b.value

fn loop_it() -> i32:
    total = 0
    for i in 0..5:
        v = List[i32]()
        v.push(i)
        if i == 1:
            continue
        if i == 4:
            break
        total += v[0]
    return total

fn main():
    print(find(5))
    print(find(1))
    print(loop_it())
"""
    ok(tmp_path, src, ["10", "7", "5"])


@needs_cc
def test_struct_with_vec_and_reassign(tmp_path):
    src = """
struct Bag:
    items: List[i32]
    name: str

fn make(n: i32) -> Bag:
    v = List[i32]()
    for i in 0..n:
        v.push(i)
    return Bag{ items: v, name: "b" }

fn eat(b: consume Bag) -> usize:
    return b.items.len

fn main():
    bag = make(3)
    print(bag.items.len)
    bag = make(5)
    print(bag.items.len)
    bag.items = List[i32]()
    print(bag.items.len)
    print(eat(bag))
"""
    # `Bag{ items: v }`: since v is a place, ownership is implicitly moved
    ok(tmp_path, src, ["3", "5", "0", "0"])


@needs_cc
def test_match_give_consumes(tmp_path):
    src = """
enum Tree:
    Leaf(i32)
    Node(Box[Tree], Box[Tree])

fn build(d: i32) -> Tree:
    if d == 0:
        return Tree.Leaf(1)
    return Tree.Node(Box[Tree](build(d - 1)), Box[Tree](build(d - 1)))

fn count(t: consume Tree) -> i32:
    match consume t:
        Leaf(v):
            return v
        Node(l, r):
            return count(l.value) + count(r.value)

fn main():
    print(count(build(4)))
"""
    # `l.value` partial move: moving Box contents is unsupported
    assert any("cannot be moved" in m for m in messages(src))

    src2 = """
enum Tree:
    Leaf(i32)
    Node(Box[Tree], Box[Tree])

fn build(d: i32) -> Tree:
    if d == 0:
        return Tree.Leaf(1)
    return Tree.Node(Box[Tree](build(d - 1)), Box[Tree](build(d - 1)))

fn count(t: Tree) -> i32:
    match t:
        Leaf(v):
            return v
        Node(l, r):
            return count(l.value) + count(r.value)

fn eat(t: consume Tree) -> i32:
    match consume t:
        Leaf(v):
            return v
        Node(l, _):
            return 2

fn main():
    t = build(4)
    print(count(t))
    print(eat(build(3)))
    print(eat(t))
"""
    ok(tmp_path, src2, ["16", "2", "2"])


@needs_cc
def test_pop_and_vec_of_vec_clear(tmp_path):
    src = """
fn main():
    outer = List[List[i32]]()
    for i in 0..3:
        inner = List[i32]()
        inner.push(i)
        inner.push(i + 1)
        outer.push(inner)
    print(outer.len)
    match outer.pop():
        Valid(v):
            print(v.len)
        None:
            print(-1)
    outer.clear()
    print(outer.len)
"""
    ok(tmp_path, src, ["3", "2", "0"])


@needs_cc
def test_try_early_return_drops(tmp_path):
    src = """
fn check(n: i32) -> Result[i32, i32]:
    if n > 2:
        return Err(n)
    return Ok(n)

fn run(n: i32) -> Result[i32, i32]:
    v = List[i32]()
    v.push(1)
    x = check(n)?
    return Ok(x + i32(v.len))

fn main():
    match run(1):
        Ok(x):
            print(x)
        Err(e):
            print(-e)
    match run(5):
        Ok(x):
            print(x)
        Err(e):
            print(-e)
"""
    ok(tmp_path, src, ["2", "-5"])


@needs_cc
def test_vec_bounds_checked_in_release(tmp_path):
    src = """
fn main():
    v = List[i32]()
    v.push(1)
    i = 3
    print(v[i])
"""
    for rel in (False, True):
        assert run(tmp_path, src, release=rel).returncode == 101


def test_errors_copy_and_partial_move():
    base = "fn main():\n    a = List[i32]()\n"
    assert any("was moved" in m for m in messages(base + "    b = a\n    print(a.len)\n"))
    assert any("was moved" in m for m in messages(base + "    b = List[i32]()\n    b = a\n    print(a.len)\n"))
    assert messages(base + "    b = a\n    print(b.len)\n") == []
    assert any("was moved" in m for m in messages(base + "    b = a\n    print(a.len)\n"))
    assert messages("fn main():\n    x = 1\n    y = x\n") == []
    assert messages("fn main():\n    v = List[List[i32]]()\n    print(v[0].len)\n") == []
    assert any("cannot be moved out" in m for m in messages(
        "fn main():\n    v = List[List[i32]]()\n    w = v[0]\n"))
    assert messages("fn main():\n    a: [2]List[i32] = [List[i32](), List[i32]()]\n") == []
    assert any("repeats one value" in m for m in messages("fn main():\n    a = [List[i32](); 2]\n"))


def test_reserved_names():
    assert any("is a reserved name" in m for m in messages("struct List:\n    x: i32\n\nfn main():\n    pass\n"))



_FRESH = """struct Maker:
    text: string
    n: i32

fn make() -> Maker:
    return Maker{ text: string.from("hello"), n: 3 }

fn nums() -> List[i32]:
    xs = List[i32]()
    xs.push(7)
    xs.push(8)
    return xs

"""


@needs_cc
@pytest.mark.parametrize("body,expected", [
    ("view = make().text.as_str()\n    print(view)", ["hello"]),
    ("print(make().text.as_str())", ["hello"]),
    ("n = make().n\n    print(n)", ["3"]),
    ("x = make().text.clone()\n    print(x.as_str())", ["hello"]),
    ("print(nums()[1])", ["8"]),
    ("print(nums().len)", ["2"]),
    ("v = nums().get(0)\n    print(v)", ["7"]),
    ("print(nums().clone().len)", ["2"]),
    ("print(Box[List[i32]](nums()).value.len)", ["2"]),
    ("for i in 0..2:\n        print(make().text.as_str())", ["hello", "hello"]),
])
def test_fresh_value_used_as_a_base_is_freed(tmp_path, body, expected):
    """A fresh owned value whose field, element, or `.len` is used is freed (the old `make().as_str()` leak)."""
    ok(tmp_path, _FRESH + "fn main():\n    " + body + "\n", expected)


def test_list_reserve(tmp_path):
    src = """
fn main():
    xs = List[i32]()
    xs.reserve(1000)
    for i in 0..1000:
        xs.push(i)
    xs.reserve(0)
    xs.reserve(5000)
    xs.push(7)
    names = List[string]()
    names.reserve(2)
    names.push("a".to_string())
    names.push("b".to_string())
    names.push("c".to_string())
    print(xs.len, xs[999], xs[1000], names.len, names[2])
"""
    ok(tmp_path, src, ["1001", "999", "7", "3", "c"])


def test_list_reserve_too_large_fails(tmp_path):
    src = """
fn main():
    xs = List[i64]()
    xs.push(1)
    xs.reserve(18446744073709551615)
    print(xs.len)
"""
    r = run(tmp_path, src)
    assert r.returncode != 0 and "out of memory" in r.stderr, r.stderr


def test_list_reserve_needs_mutable_list(tmp_path):
    src = """
fn main():
    fixed xs = List[i32]()
    xs.reserve(3)
    print(xs.len)
"""
    r = run(tmp_path, src)
    assert r.returncode != 0 and "fixed" in r.stderr, r.stderr
