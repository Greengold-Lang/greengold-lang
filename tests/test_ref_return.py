"""`-> ref T` (derived from input) and List.get: non-owning views."""
import pytest

from .helpers import HAS_CC, messages
from .test_heap import ok, run

needs_cc = pytest.mark.skipif(not HAS_CC, reason="No C compiler")

STORE = """
struct Store:
    items: List[List[i32]]
    name: str

fn first_inner(s: Store) -> ref List[i32]:
    return s.items.get(0)

fn name_of(s: Store) -> ref str:
    return s.name

fn make() -> Store:
    items = List[List[i32]]()
    a = List[i32]()
    a.push(4)
    a.push(5)
    items.push(a)
    return Store{ items: items, name: "dep" }
"""


@needs_cc
def test_view_of_heap_value_no_leak_no_double_free(tmp_path):
    src = STORE + """
fn main():
    s = make()
    print(first_inner(s).len)
    print(first_inner(s)[1])
    print(s.items.get(0)[0])
    print(name_of(s))
    match Valid(3):
        Valid(n):
            print(n)
        None:
            pass
"""
    ok(tmp_path, src, ["2", "5", "4", "dep", "3"])


@needs_cc
def test_vec_get_bounds_checked(tmp_path):
    src = "fn main():\n    v = List[i32]()\n    v.push(1)\n    i = usize(2)\n    print(v.get(i))\n"
    for rel in (False, True):
        assert run(tmp_path, src, release=rel).returncode == 101


def test_inferred_binding_stores_the_reference():
    assert messages(STORE + "fn main():\n    s = make()\n    x = first_inner(s)\n    print(x.len)\n") == []
    assert any("view" in m for m in messages(STORE + "fn main():\n    s = make()\n    x: List[i32] = first_inner(s)\n"))
    assert any("view" in m or "move" in m for m in messages(
        "fn main():\n    v = List[List[i32]]()\n    w = List[List[i32]]()\n    w.push(v.get(0))\n"))


def test_view_return_derives_from_one_read_or_lend_param():
    second = "struct A:\n    v: List[i32]\n\nfn f(a: A, b: A) -> ref List[i32]:\n    return b.v\n\nfn main():\n    pass\n"
    assert messages(second) == []
    mixed = ("struct A:\n    v: List[i32]\n\nfn f(a: A, b: A) -> ref List[i32]:\n"
             "    if true:\n        return a.v\n    return b.v\n")
    assert any("more than one parameter" in m for m in messages(mixed))
    local = "fn f(a: read i32) -> ref i32:\n    x = 1\n    return x\n"
    assert any("parameter" in m for m in messages(local))
    assert any("at least one parameter" in m for m in messages("fn f() -> ref i32:\n    return 1\n"))
    assert any("read" in m or "lend" in m for m in messages(
        "fn f(a: consume List[i32]) -> ref List[i32]:\n    return a\n"))
    assert any("read" in m or "lend" in m for m in messages("fn f(a: i32) -> ref i32:\n    return a\n"))


def test_view_is_read_only():
    src = STORE + "fn main():\n    s = make()\n    first_inner(s).push(1)\n"
    assert messages(src) != []


PLAYER = """
struct Player:
    hp: i32

struct Slot:
    who: read Player tied to self

struct Hold:
    buf: lend List[i32] tied to self
"""


@needs_cc
def test_stored_read_and_lend_locals(tmp_path):
    src = PLAYER + """
fn main():
    hero = Player{ hp: 3 }
    r: read Player = hero
    r2 = read hero
    print(r.hp)
    print(r2.hp)
    w: lend Player = hero
    w.hp = 8
    print(hero.hp)
    other = Player{ hp: 1 }
    w2: lend Player = hero
    w2 = other
    w2.hp = 4
    print(hero.hp)
    print(other.hp)
"""
    ok(tmp_path, src, ["3", "3", "8", "8", "4"])


@needs_cc
def test_ref_field_and_lend_through_field(tmp_path):
    src = PLAYER + """
fn main():
    hero = Player{ hp: 2 }
    s = Slot{ who: hero }
    print(s.who.hp)
    items = List[i32]()
    h = Hold{ buf: items }
    h.buf.push(7)
    print(items.len)
    print(items[0])
"""
    ok(tmp_path, src, ["2", "1", "7"])


@needs_cc
def test_lend_return_and_tied_to(tmp_path):
    src = PLAYER + """
fn hp_of(p: lend Player) -> lend i32:
    return p.hp

fn pick(a: read Player, b: read Player) -> ref Player tied to b:
    return b

fn main():
    hero = Player{ hp: 1 }
    w = hp_of(hero)
    print(w)
    ally = Player{ hp: 6 }
    seen = pick(hero, ally)
    print(seen.hp)
"""
    ok(tmp_path, src, ["1", "6"])


def test_scope_escape_and_live_reference_block_move():
    escape = """
fn main():
    hero = 1
    slot: read i32 = hero
    if true:
        inner = 2
        slot = inner
    print(slot)
"""
    assert any("does not live long enough" in m for m in messages(escape))
    live = """
fn take(c: consume List[i32]):
    print(c.len)

fn main():
    v = List[i32]()
    v.push(1)
    r = v.get(0)
    take(v)
    print(r)
"""
    assert any("moved" in m or "tied" in m for m in messages(live))
    exclusive = """
fn main():
    x = 1
    w: lend i32 = x
    print(x)
    print(w)
"""
    assert any("lend" in m for m in messages(exclusive))
    shared = """
fn main():
    x = 1
    r: read i32 = x
    print(x)
    print(r)
"""
    assert messages(shared) == []
    moved_ok = """
fn take(c: consume List[i32]):
    print(c.len)

fn main():
    v = List[i32]()
    v.push(1)
    take(v)
"""
    assert messages(moved_ok) == []
