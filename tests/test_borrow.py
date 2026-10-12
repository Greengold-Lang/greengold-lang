"""Borrow checker tests: consume / read / lend / tied to and implicit move rules."""
from .helpers import PREAMBLE, messages, with_main


def has(msgs, text):
    return any(text in m for m in msgs)


def test_own_moves_value():
    msgs = messages(with_main("c = Counter{ value: 1 }\nfinish(c)\nshow(c)"))
    assert has(msgs, "was moved")


def test_move_in_if_branch_is_visible_after():
    msgs = messages(with_main("c = Counter{ value: 1 }\nf = true\nif f:\n    finish(c)\nshow(c)"))
    assert has(msgs, "was moved")


def test_move_in_loop_is_rejected():
    msgs = messages(with_main("c = Counter{ value: 1 }\nfor i in 0..3:\n    finish(c)"))
    assert msgs


def test_use_before_move_is_fine():
    assert messages(with_main("c = Counter{ value: 1 }\nshow(c)\nfinish(c)")) == []


def test_lend_requires_var():
    msgs = messages(with_main("fixed c = Counter{ value: 0 }\nbump(c)"))
    assert has(msgs, "declared `fixed`")
    assert not messages(with_main("c = Counter{ value: 0 }\nbump(c)"))


def test_lend_twice_in_one_call_rejected():
    src = ("struct P:\n    a: i32\n\nfn two(x: lend P, y: lend P):\n    x.a = 1\n\n"
           "fn main():\n    p = P{ a: 1 }\n    two(p, p)\n")
    assert has(messages(src), "multiple times")


def test_read_param_is_immutable():
    src = "struct P:\n    a: i32\n\nfn f(p: read P):\n    p.a = 1\n\nfn main():\n    f(P{ a: 1 })\n"
    assert messages(src)


def test_cannot_move_from_lend_param():
    src = PREAMBLE + "fn f(c: lend Counter):\n    finish(c)\n\nfn main():\n    print(1)\n"
    assert has(messages(src), "you do not own it")


def test_primitive_consume_is_rejected():
    assert has(messages("fn eat(n: consume i32):\n    print(n)\n\nfn main():\n    eat(1)\n"), "is copied")


def test_heap_assignment_moves_source():
    msgs = messages("fn main():\n    a = List[i32]()\n    b = a\n    print(a.len)\n")
    assert has(msgs, "can no longer be used")


def test_explicit_copy_is_allowed():
    assert messages("fn main():\n    a = [1, 2, 3]\n    b = copy a\n    print(b[0])\n") == []


def test_tied_to_requires_binding_for_reference_field():
    msgs = messages("struct P:\n    a: i32\n\nstruct Q:\n    r: lend P\n\nfn main():\n    print(1)\n")
    assert msgs


def test_lend_rejected_when_struct_holding_read_ref_is_passed_in_same_call():
    src = """struct Player:
    hp: i32

struct Slot:
    who: read Player tied to self

fn f(a: lend Player, s: read Slot) -> i32:
    a.hp = 5
    return s.who.hp

fn main():
    hero = Player{ hp: 1 }
    s = Slot{ who: hero }
    print(f(hero, s))
"""
    assert any("is still tied to it" in m for m in messages(src))


def test_reading_holder_then_assigning_referent_in_one_statement_is_allowed():
    src = """struct Player:
    hp: i32

struct Slot:
    who: read Player tied to self

fn main():
    hero = Player{ hp: 1 }
    s = Slot{ who: hero }
    hero.hp = s.who.hp + 1
    print(hero.hp)
"""
    assert messages(src) == []
