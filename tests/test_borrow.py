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


# Views (`str`, slices, and values that hold them) borrow the variable they were made from.
_VIEW_ESCAPES = {
    "outer_scope": 't = "x"\nif true:\n    s = string("hi")\n    t = s.as_str()\nprint(t)',
    "slice_range": 'xs = List[str]()\nif true:\n    s = string("hi")\n    xs.push(s[0..1])\nprint(xs[0])',
    "optional": 'o: Optional[str] = None\nif true:\n    s = string("hi")\n    o = Valid(s.as_str())\nmatch o:\n    Valid(x):\n        print(x)\n    None:\n        print("n")',
    "loop": 't = "x"\nfor i in 0..2:\n    s = string("hi")\n    t = s.trim()\nprint(t)',
}


def test_view_cannot_outlive_its_string():
    for name, body in _VIEW_ESCAPES.items():
        assert has(messages(with_main(body)), "does not live long enough"), name


def test_view_blocks_change_and_move_of_its_string():
    assert has(messages(with_main('s = string("hi")\nt = s.as_str()\ns.clear()\nprint(t)')), "still")
    assert has(messages(with_main('s = string("hi")\nt = s.as_str()\nu = s\nprint(t)')), "still tied")


# A view stored in a branch of an `if` or `match` stays tied after the branch (found by tools/fuzz_views.py).
def test_view_made_in_a_branch_stays_tied_after_it():
    cases = {
        "if": 's = string("abc")\nv = "lit"\nif s.len > 1:\n    v = s.as_str()\ns.clear()\nprint(v)',
        "match": 's = string("abc")\nv = "lit"\nmatch s.len:\n    3:\n        v = s.as_str()\n    _:\n        print("x")\ns = string("zzz")\nprint(v)',
        "nested": 's = string("abc")\nv = "lit"\nif s.len > 1:\n    if s.len > 2:\n        v = s.as_str()\ns = string("q")\nprint(v)',
        "loop_carried": 'o = string("d")\nv = "lit"\nfor i in 0..2:\n    if true:\n        o = string("n")\n        print(v)\n        v = o.as_str()',
    }
    for name, body in cases.items():
        assert has(messages(with_main(body)), "still tied"), name


def test_view_made_in_a_branch_of_its_own_scope_is_not_kept():
    src = 'if true:\n    s = string("abc")\n    v = s.as_str()\n    print(v)\ns = string("q")\nprint(s.len)'
    assert messages(with_main(src)) == []


# A view kept in a variable of an outer scope is only a problem if it is still tied to the inner variable
# and read again after that variable is gone.
def test_view_in_outer_variable_that_is_not_read_again_is_fine():
    cases = {
        "used_in_loop_only": 'line = ""\nfor i in 0..3:\n    s = string("  hi  ")\n    line = s.trim()\n    print(line)',
        "used_in_branch_only": 'best = ""\nfor i in 0..3:\n    s = string("hi")\n    if s.len > 1:\n        best = s.trim()\n        print(best)\nprint("done")',
        "never_used": 't = "x"\nif true:\n    s = string("hello")\n    t = s.as_str()',
        "overwritten_in_block": 'if true:\n    s = string("abc")\n    v = "x"\n    v = s.as_str()\n    v = "lit"\nprint(1)',
    }
    for name, body in cases.items():
        assert messages(with_main(body)) == [], name


def test_view_in_outer_variable_read_again_is_rejected():
    cases = {
        "after_block": 't = "x"\nif true:\n    s = string("hi")\n    t = s.as_str()\nprint(t)',
        "next_iteration": 'v = "lit"\nfor i in 0..2:\n    print(v)\n    s = string("hi")\n    v = s.as_str()',
        "after_loop": 'v = "lit"\nfor i in 0..2:\n    s = string("hi")\n    v = s.as_str()\nprint(v)',
        "held_by_list": 'xs = List[str]()\nfor i in 0..2:\n    s = string("hi")\n    xs.push(s.as_str())\nprint(xs.len)',
    }
    for name, body in cases.items():
        assert has(messages(with_main(body)), "does not live long enough"), name


# The result of a call to a user function points only into the arguments its `return` values can come from.
_FLOW_FNS = {
    "via_local": ("fn via_local(a: str, b: str) -> str:\n    x = b\n    return x\n", 't = via_local("q", s.as_str())'),
    "via_struct": ("struct W:\n    name: str\nfn via_struct(a: str, b: str) -> str:\n    p = W{ name: b }\n    return p.name\n",
                   't = via_struct("q", s.as_str())'),
    "via_lend": ("fn via_lend(out: lend List[str], a: str, b: str) -> str:\n    out.push(b)\n    return out[0]\n",
                 'xs = List[str]()\nt = via_lend(xs, "q", s.as_str())'),
    "either": ("fn either(c: bool, a: str, b: str) -> str:\n    if c:\n        return a\n    return b\n",
               't = either(false, "q", s.as_str())'),
    "recursive": ("fn rec(n: i32, a: str, b: str) -> str:\n    if n == 0:\n        return b\n    return rec(n - 1, b, a)\n",
                  't = rec(3, "q", s.as_str())'),
    "closure": ("fn viaclo(a: str, b: str) -> str:\n    g = fn() -> str => b\n    return g()\n",
                't = viaclo("q", s.as_str())'),
    "generic": ("fn gen2[T](a: T, b: T) -> T:\n    return b\n", 't = gen2("q", s.as_str())'),
    "nested": ("fn two(a: str, b: str) -> str:\n    return a\nfn nest(a: str, b: str) -> str:\n    return two(b, a)\n",
               't = nest("q", s.as_str())'),
}


def _escape_case(fns: str, call: str) -> str:
    inner = "\n".join("    " + l for l in call.splitlines())
    return with_main(f't = "x"\nif true:\n    s = string("hello")\n{inner}\nprint(t)', PREAMBLE + fns)


def test_call_result_ties_to_each_argument_it_can_return():
    for name, (fns, call) in _FLOW_FNS.items():
        assert has(messages(_escape_case(fns, call)), "does not live long enough"), name


def test_call_result_does_not_tie_to_an_argument_it_never_returns():
    fns = "fn first(a: str, b: str) -> str:\n    return a\nfn lit(a: str) -> str:\n    return \"static\"\n"
    for call in ('t = first("q", s.as_str())', 't = lit(s.as_str())'):
        assert messages(_escape_case(fns, call)) == [], call
    # ... and the argument it does return still ties
    assert has(messages(_escape_case(fns, 't = first(s.as_str(), "q")')), "does not live long enough")


def test_storing_into_a_field_is_not_a_read_of_the_struct():
    src = ('struct W:\n    name: str\n\nfn main():\n    w = W{ name: "x" }\n    for i in 0..3:\n'
           '        s = string("hi")\n        w.name = s.as_str()\n')
    assert messages(PREAMBLE + src) == []
    assert has(messages(PREAMBLE + src + "    print(w.name)\n"), "does not live long enough")


def test_block_that_returns_does_not_leak_its_views():
    src = 'v = "x"\nfor i in 0..2:\n    s = string("hi")\n    v = s.as_str()\n    return\nprint(1)'
    assert messages(with_main(src)) == []
