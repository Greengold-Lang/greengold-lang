"""Type checking: valid programs must pass without errors, type inference must work correctly."""
import pytest

from greengold.ast_nodes import VarDecl

from .helpers import front_end, messages, with_main


def ok(src: str):
    program, diags = front_end(src)
    assert not diags, [d.message for d in diags]
    return program


def main_decl(program):
    return next(d for d in program.decls if getattr(d, "name", "") == "main")


def test_player_example_ok():
    ok("""struct Player:
    x: f32
    y: f32
    health: i32

impl Player:
    fn take_damage(self: lend Player, amount: i32):
        self.health -= amount

fn main():
    player = Player{
        x: 100.0
        y: 200.0
        health: 100
    }

    player.take_damage(25)
    print(player.health)
""")


def test_modes_example_ok():
    ok(with_main("c = Counter{ value: 0 }\nbump(c)\nbump(c)\nshow(c)\nfinish(c)"))


def test_inference_defaults():
    prog = ok("fn main():\n    a = 5\n    b = 5.0\n    c = true\n    d = \"s\"\n")
    tys = [s.ty for s in main_decl(prog).body if isinstance(s, VarDecl)]
    assert tys == ["i32", "f64", "bool", "str"]


def test_literal_adapts_to_declared_type():
    prog = ok("fn main():\n    a: i64 = 5\n    b: f32 = 1.5\n    c: i64 = 2 + 3\n")
    assert [s.ty for s in main_decl(prog).body] == ["i64", "f32", "i64"]


def test_literal_adapts_to_other_operand():
    ok("fn f(x: i64, y: f32) -> f32:\n    if 1 < x:\n        return 2.0 * y\n    return y + 1.0\n\n"
       "fn main():\n    print(f(3, 1.5))\n")


def test_no_implicit_conversion():
    # Only conversions that keep every value are implicit: `i64` to `i32` and `i32` with `u64` are not.
    assert any("Type mismatch" in m for m in messages(
        "fn main():\n    a: i64 = 1\n    b: i32 = a\n"))
    assert any("same type" in m for m in messages(
        "fn main():\n    a: i32 = 1\n    b: u64 = 2\n    print(a + b)\n"))
    assert messages("fn main():\n    a: i32 = 1\n    b: i64 = a\n    print(a + b)\n") == []


def test_int_literal_for_float_gives_hint():
    from .helpers import front_end as fe
    _, diags = fe("fn main():\n    x: f32 = 5\n")
    assert diags and "5.0" in (diags[0].hint or "")


def test_for_loop_variable_immutable():
    assert any("loop counter" in m for m in messages(
        "fn main():\n    for i in 0..3:\n        i = 5\n"))


def test_for_range_types():
    ok("fn main():\n    n: i64 = 3\n    for i in 0..=n:\n        print(i)\n")


def test_break_outside_loop():
    assert any("inside a loop" in m for m in messages("fn main():\n    break\n"))


def test_return_type_checked():
    assert any("Type mismatch" in m for m in messages(
        "fn f() -> i32:\n    return true\n\nfn main():\n    print(f())\n"))


def test_condition_must_be_bool():
    assert any("Condition must be `bool`" in m for m in messages("fn main():\n    if 1:\n        print(1)\n"))


def test_missing_main():
    assert any("main" in m for m in messages("fn f():\n    print(1)\n"))


def test_missing_struct_field():
    assert any("Missing field" in m for m in messages(
        "struct P:\n    a: i32\n    b: i32\n\nfn main():\n    p = P{ a: 1 }\n"))


def test_void_value_rejected():
    assert any("does not return a value" in m for m in messages(
        "fn f():\n    print(1)\n\nfn main():\n    x = f()\n"))


def test_no_shadowing():
    assert any("already defined" in m for m in messages(
        "fn main():\n    x = 1\n    if true:\n        x: i32 = 2\n"))
    assert any("already defined" in m for m in messages(
        "fn main():\n    x = 1\n    if true:\n        fixed x = 2\n"))


def test_recursive_struct_rejected():
    assert any("infinite size" in m for m in messages(
        "struct A:\n    a: A\n\nfn main():\n    print(1)\n"))


def test_lend_primitive_works():
    ok("fn inc(n: lend i32):\n    n += 1\n\nfn main():\n    x = 1\n    inc(x)\n    print(x)\n")


def test_lend_passthrough_and_read_from_lend_param():
    ok(PREAMBLE_SHOW + "fn twice(c: lend Counter):\n    bump(c)\n    show(c)\n\n"
       "fn main():\n    c = Counter{ value: 0 }\n    twice(c)\n")


PREAMBLE_SHOW = """struct Counter:
    value: i32

fn show(c: Counter):
    print(c.value)

fn bump(c: lend Counter):
    c.value += 1

"""


def test_lend_field_of_mut_var():
    ok("struct In:\n    v: i32\n\nstruct Out:\n    i: In\n\nfn bump(x: lend In):\n    x.v += 1\n\n"
       "fn main():\n    o = Out{ i: In{ v: 1 } }\n    bump(o.i)\n    print(o.i.v)\n")


# --- move analysis ---

MOVE_PRE = PREAMBLE_SHOW + "fn finish(c: consume Counter):\n    print(c.value)\n\n"


def test_reassign_after_give_allowed():
    ok(MOVE_PRE + "fn main():\n    c = Counter{ value: 1 }\n    finish(c)\n"
       "    c = Counter{ value: 2 }\n    show(c)\n")


def test_branch_with_return_does_not_poison():
    ok(MOVE_PRE + "fn f(flag: bool):\n    c = Counter{ value: 1 }\n    if flag:\n        finish(c)\n"
       "        return\n    show(c)\n\nfn main():\n    f(true)\n")


def test_else_branch_move_counts():
    assert any("was moved" in m for m in messages(
        MOVE_PRE + "fn main():\n    c = Counter{ value: 1 }\n    flag = true\n    if flag:\n        print(1)\n"
        "    else:\n        finish(c)\n    show(c)\n"))


def test_give_inside_loop_of_inner_variable_ok():
    ok(MOVE_PRE + "fn main():\n    for i in 0..3:\n        c = Counter{ value: i }\n        finish(c)\n")


def test_double_give_same_call():
    assert any("was moved" in m for m in messages(
        MOVE_PRE + "fn two(a: consume Counter, b: consume Counter):\n    print(1)\n\n"
        "fn main():\n    c = Counter{ value: 1 }\n    two(c, c)\n"))


def test_copyable_value_param_can_be_given_away():
    ok(MOVE_PRE + "fn f(c: Counter):\n    finish(c)\n\nfn main():\n    print(1)\n")


def test_read_param_cannot_be_given_away():
    assert any("cannot be moved" in m for m in messages(
        MOVE_PRE + "fn f(c: read Counter):\n    finish(c)\n\nfn main():\n    print(1)\n"))


def test_give_param_is_mutable_and_movable():
    ok(MOVE_PRE + "fn f(c: consume Counter):\n    c.value = 9\n    finish(c)\n\nfn main():\n    print(1)\n")


def test_partial_move_field():
    src = ("struct In:\n    v: i32\n\nstruct Out:\n    a: In\n    b: In\n\n"
           "fn eat(x: consume In):\n    print(x.v)\n\n")
    ok(src + "fn main():\n    o = Out{ a: In{ v: 1 }, b: In{ v: 2 } }\n    eat(o.a)\n    print(o.b.v)\n")
    assert any("was moved" in m for m in messages(
        src + "fn main():\n    o = Out{ a: In{ v: 1 }, b: In{ v: 2 } }\n    eat(o.a)\n    print(o.a.v)\n"))


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "%"])
def test_arithmetic_ints_ok(op):
    ok(f"fn main():\n    print(7 {op} 2)\n")


def test_modulo_float_rejected():
    assert any("integer" in m for m in messages("fn main():\n    print(7.0 % 2.0)\n"))
