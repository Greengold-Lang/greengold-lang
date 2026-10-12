"""enum declaration, variant constructors, methods and match (non-generic)."""
import pytest

from greengold.ast_nodes import EnumDecl, Match
from greengold.cli import compile_to_ir
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse

from .helpers import HAS_CC, front_end, messages, run_example, run_gg_source

needs_cc = pytest.mark.skipif(not HAS_CC, reason="gcc/clang not found")


SHAPE = """\
enum Shape:
    Circle(f32)
    Rect(f32, f32)
    Empty

"""


def has(msgs: list[str], text: str) -> bool:
    return any(text in m for m in msgs)


def parse_src(src: str):
    diags = DiagnosticBag()
    prog = parse(tokenize(src, diags), diags)
    return prog, [d.message for d in diags.items]


# ---------------------------------------------------------------- lexer / parser

def test_lexer_keywords():
    kinds = [t.kind for t in tokenize("match enum pass\n", DiagnosticBag())]
    assert kinds[:3] == ["match", "enum", "pass"]


def test_parse_enum_decl():
    prog, errs = parse_src(SHAPE + "fn main():\n    pass\n")
    assert not errs
    d = prog.decls[0]
    assert isinstance(d, EnumDecl) and d.name == "Shape"
    assert [(v.name, len(v.payload)) for v in d.variants] == [("Circle", 1), ("Rect", 2), ("Empty", 0)]


def test_parse_match_arms_and_modes():
    src = """fn f(s: Shape):
    match lend s:
        Circle(r):
            pass
        Shape.Rect(w, _):
            pass
        _:
            pass
"""
    prog, errs = parse_src(src)
    assert not errs
    m = prog.decls[0].body[0]
    assert isinstance(m, Match) and m.mode == "lend"
    assert [(a.variant, a.qualifier, [b.name for b in a.bindings]) for a in m.arms] == [
        ("Circle", None, ["r"]), ("Rect", "Shape", ["w", "_"]), (None, None, [])]


def test_parse_match_give_and_expression_scrutinee():
    prog, errs = parse_src("fn f():\n    match g():\n        _:\n            pass\n    match consume x:\n        _:\n            pass\n")
    assert not errs
    assert [s.mode for s in prog.decls[0].body] == ["", "consume"]


def test_parse_empty_arm_body_error():
    _, errs = parse_src("fn f(s: Shape):\n    match s:\n        Empty:\n        _:\n            pass\n")
    assert any("body is empty" in e for e in errs)


def test_parse_enum_without_variants():
    _, errs = parse_src("enum E:\n    pass\n")
    assert errs  # `pass` is not a variant name


def test_parse_enum_explicit_numbers():
    _, errs = parse_src("enum E:\n    A = 1\n    B\n")
    assert errs == []


def test_parse_enum_named_fields_error():
    _, errs = parse_src("enum E:\n    A(x: i32)\n")
    assert any("Named variant fields" in e for e in errs)


def test_parse_enum_payload_lend_error():
    _, errs = parse_src("enum E:\n    A(lend i32)\n")
    assert any("cannot be an enum payload" in e for e in errs)


def test_parse_enum_empty_payload_parens():
    _, errs = parse_src("enum E:\n    A()\n")
    assert any("empty payload parentheses" in e for e in errs)


# ---------------------------------------------------------------- type checking: accepted

def test_ok_basic_program():
    src = SHAPE + """fn area(s: Shape) -> f32:
    match s:
        Circle(r):
            return 3.0 * r * r
        Rect(w, h):
            return w * h
        Empty:
            return 0.0

fn main():
    print(area(Shape.Circle(1.0)))
"""
    assert messages(src) == []


def test_ok_all_arms_return_needs_no_trailing_return():
    src = SHAPE + """fn f(s: Shape) -> i32:
    match s:
        Circle(_):
            return 1
        _:
            return 2

fn main():
    print(f(Shape.Empty))
"""
    assert messages(src) == []


def test_ok_arm_with_panic_counts_as_return():
    src = SHAPE + """fn f(s: Shape) -> i32:
    match s:
        Circle(_):
            return 1
        Rect(_, _):
            panic("rect olmaz")
        Empty:
            return 0

fn main():
    print(f(Shape.Empty))
"""
    assert messages(src) == []


def test_error_arm_does_not_return_means_missing_return():
    src = SHAPE + """fn f(s: Shape) -> i32:
    match s:
        Circle(_):
            return 1
        _:
            pass

fn main():
    print(f(Shape.Empty))
"""
    assert has(messages(src), "not all paths have a `return`")



def test_ok_enum_method_read_and_lend():
    src = SHAPE + """impl Shape:
    fn area(self: Shape) -> f32:
        match self:
            Circle(r):
                return r
            _:
                return 0.0

    fn reset(self: lend Shape):
        self = Shape.Empty

fn main():
    s = Shape.Circle(2.0)
    print(s.area())
    s.reset()
    print(s.area())
"""
    assert messages(src) == []


def test_ok_variant_name_may_equal_local_or_function():
    src = SHAPE + """fn Empty() -> i32:
    return 1

fn main():
    Rect = 5
    s = Shape.Rect(1.0, 2.0)
    match s:
        Rect(a, b):
            print(a + b)
        _:
            pass
    print(Rect + Empty())
"""
    assert messages(src) == []


def test_ok_payload_struct_enum_array_and_string():
    src = """struct P:
    x: i32

enum Inner:
    A
    B

enum Outer:
    S(P)
    E(Inner)
    Arr([3]i32)
    Name(str)

fn main():
    o = Outer.Arr([1, 2, 3])
    p = Outer.S(P{ x: 4 })
    e = Outer.E(Inner.B)
    n = Outer.Name("hi")
    match o:
        Arr(a):
            print(a[1])
        _:
            pass
"""
    assert messages(src) == []


def test_ok_qualified_pattern():
    src = SHAPE + """fn main():
    s = Shape.Empty
    match s:
        Shape.Circle(_):
            pass
        Shape.Rect(_, _):
            pass
        Shape.Empty:
            pass
"""
    assert messages(src) == []


def test_ok_match_lend_passes_binding_to_other_call():
    src = SHAPE + """fn bump(x: lend f32):
    x += 1.0

fn grow(s: lend Shape):
    match lend s:
        Circle(r):
            bump(r)
        _:
            pass

fn main():
    s = Shape.Circle(1.0)
    grow(s)
"""
    assert messages(src) == []


def test_ok_match_give_binding_is_mutable_owner_and_returnable():
    src = SHAPE + """fn take(s: consume Shape) -> f32:
    match consume s:
        Circle(r):
            r += 1.0
            return r
        _:
            return 0.0

fn main():
    s = Shape.Circle(1.0)
    print(take(s))
"""
    assert messages(src) == []


def test_ok_move_in_arm_other_arm_unaffected():
    src = """struct Crate:
    v: i32

enum E:
    A
    B

fn eat(b: consume Crate):
    print(b.v)

fn main():
    b = Crate{ v: 1 }
    match E.A:
        A:
            eat(b)
            return
        B:
            print(b.v)
"""
    assert messages(src) == []


# ---------------------------------------------------------------- type checking: errors

def test_err_missing_variants():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Circle(_):
            pass

fn main():
    pass
"""
    msgs = messages(src)
    assert "match does not cover all cases: missing `Rect`, `Empty`" in msgs
    d = front_end(src)[1][0]
    assert "_:" in d.hint and "Rect(_, _):" in d.hint


def test_err_duplicate_arm():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Empty:
            pass
        Empty:
            pass
        _:
            pass
"""
    assert has(messages(src), "duplicate arm")


def test_err_arm_after_wildcard():
    src = SHAPE + """fn f(s: Shape):
    match s:
        _:
            pass
        Empty:
            pass
"""
    assert has(messages(src), "unreachable arm")


def test_err_redundant_wildcard():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Circle(_):
            pass
        Rect(_, _):
            pass
        Empty:
            pass
        _:
            pass
"""
    assert has(messages(src), "redundant `_` arm")


def test_err_unknown_variant():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Foo:
            pass
        _:
            pass
"""
    assert "`Foo` is not a variant of this enum." in messages(src)


def test_err_wrong_field_count_too_many():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Circle(a, b):
            pass
        _:
            pass
"""
    assert has(messages(src), "`Circle` variant has 1 payload field(s), pattern has 2 name(s)")


def test_err_payload_variant_without_names():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Circle:
            pass
        _:
            pass

fn main():
    pass
"""
    d = front_end(src)[1][0]
    assert "pattern has 0 name(s)" in d.message and "Circle(_):" in d.hint


def test_err_names_on_payloadless_variant():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Empty(x):
            pass
        _:
            pass
"""
    assert has(messages(src), "variant has no payload")


def test_err_match_on_non_enum():
    src = "fn main():\n    x = 5.5\n    match x:\n        _:\n            pass\n"
    assert has(messages(src), "can only be used on enum, integer, char, bool and string values")


def test_err_match_lend_on_immutable():
    src = SHAPE + """fn main():
    fixed s = Shape.Empty
    match lend s:
        _:
            pass
"""
    msgs = messages(src)
    assert (has(msgs, "cannot be `lend`ed") or has(msgs, "cannot `lend`")) and (has(msgs, "declared `fixed`"))


def test_err_match_lend_on_non_place():
    src = SHAPE + """fn main():
    match lend Shape.Empty:
        _:
            pass
"""
    assert has(messages(src), "must be addressable")


def test_err_use_after_match_give():
    src = SHAPE + """fn main():
    s = Shape.Circle(1.0)
    match consume s:
        _:
            pass
    match s:
        _:
            pass
"""
    assert has(messages(src), "was moved (`consume`)")


def test_err_match_give_marks_moved_even_when_only_one_arm_binds():
    src = SHAPE + """fn use_it(s: Shape):
    pass

fn main():
    s = Shape.Empty
    match consume s:
        Circle(r):
            print(r)
        _:
            pass
    use_it(s)
"""
    assert has(messages(src), "was moved (`consume`)")


def test_match_consume_on_copyable_value_param_is_allowed():
    src = SHAPE + """fn f(s: Shape):
    match consume s:
        _:
            pass

fn main():
    pass
"""
    assert messages(src) == []  # a copyable by-value parameter is the function's own copy


def test_err_match_give_from_lend_param():
    src = SHAPE + """fn f(s: lend Shape):
    match consume s:
        _:
            pass

fn main():
    pass
"""
    assert has(messages(src), "cannot be moved: `s` is a borrowed")


def test_err_read_binding_is_immutable():
    src = SHAPE + """fn f(s: Shape):
    match s:
        Circle(r):
            r += 1.0
        _:
            pass
"""
    assert has(messages(src), "`r` is a value parameter (immutable)")


def test_lend_binding_can_be_stored_as_reference():
    src = SHAPE + """fn f(s: lend Shape):
    match lend s:
        Circle(r):
            keep: lend f32 = r
            c = keep
        _:
            pass

fn main():
    pass
"""
    assert messages(src) == []


def test_lend_binding_copy_is_a_plain_value():
    # Same rule as parameter modes: `lend` parameter value can be read and copied.
    src = SHAPE + """fn f(s: lend Shape) -> f32:
    match lend s:
        Circle(r):
            c = r
            return c
        _:
            return 0.0

fn main():
    pass
"""
    assert messages(src) == []


def test_err_lend_binding_aliasing_with_scrutinee():
    src = SHAPE + """fn both(a: lend f32, s: lend Shape):
    a += 1.0

fn g(s: lend Shape):
    match lend s:
        Circle(r):
            both(r, s)
        _:
            pass
"""
    assert has(messages(src), "conflicting memory access") or has(messages(src), "cannot be borrowed")



def test_lend_bindings_of_distinct_fields_do_not_alias():
    src = SHAPE + """fn two(a: lend f32, b: lend f32):
    a += b

fn g(s: lend Shape):
    match lend s:
        Rect(w, h):
            two(w, h)
        _:
            pass

fn main():
    pass
"""
    assert messages(src) == []


def test_err_give_outer_var_in_loop_match_arm():
    src = """struct Crate:
    v: i32

enum E:
    A

fn eat(b: consume Crate):
    print(b.v)

fn main():
    b = Crate{ v: 1 }
    for i in 0..3:
        match E.A:
            A:
                eat(b)
"""
    assert has(messages(src), "defined outside the loop")


def test_err_moved_in_arm_is_moved_after_match():
    src = """struct Crate:
    v: i32

enum E:
    A
    B

fn eat(b: consume Crate):
    print(b.v)

fn main():
    b = Crate{ v: 1 }
    match E.A:
        A:
            eat(b)
        B:
            pass
    print(b.v)
"""
    assert has(messages(src), "`b` variable was moved (`consume`)")


def test_err_enum_contains_itself():
    src = "enum L:\n    Cons(i32, L)\n    Nil\n\nfn main():\n    pass\n"
    assert "enum cannot contain itself by value (heap coming in v3)." in messages(src)


def test_err_enum_contains_itself_through_struct_and_array():
    src = """struct W:
    items: [2]E

enum E:
    A(W)
    B

fn main():
    pass
"""
    assert has(messages(src), "contains itself by value") or has(messages(src), "infinite size")


def test_err_duplicate_variant_name():
    src = "enum E:\n    A\n    A(i32)\n\nfn main():\n    pass\n"
    assert has(messages(src), "defined twice in enum")


def test_err_enum_payload_slice():
    src = "enum E:\n    A([]i32)\n\nfn main():\n    pass\n"
    assert has(messages(src), "cannot be an enum payload")


def test_err_enum_payload_unknown_type():
    src = "enum E:\n    A(Nope)\n\nfn main():\n    pass\n"
    assert has(messages(src), "Unknown type `Nope`")


def test_err_bare_variant_call_needs_qualification():
    src = SHAPE + "fn main():\n    s = Circle(1.0)\n"
    msgs = messages(src)
    assert has(msgs, "`Circle` is a variant name; qualifier is required")
    assert front_end(src)[1][0].hint == "Write `Shape.Circle(...)` (variants are qualified by enum name)."


def test_err_bare_variant_name_needs_qualification():
    src = SHAPE + "fn main():\n    s = Empty\n"
    assert has(messages(src), "`Empty` is a variant name")


def test_err_unknown_variant_constructor():
    src = SHAPE + "fn main():\n    s = Shape.Circel(1.0)\n"
    d = front_end(src)[1][0]
    assert "`Shape` enum has no variant named `Circel`" in d.message
    assert "Circle" in d.hint


def test_err_variant_ctor_wrong_arg_type():
    src = SHAPE + 'fn main():\n    s = Shape.Circle("x")\n'
    assert has(messages(src), "Type mismatch")


def test_err_variant_ctor_wrong_arg_count():
    src = SHAPE + "fn main():\n    s = Shape.Rect(1.0)\n"
    assert has(messages(src), "expected 2 arguments, found 1") or has(messages(src), "expects 2 argument")


def test_err_payload_variant_without_args():
    src = SHAPE + "fn main():\n    s = Shape.Circle\n"
    assert has(messages(src), "payload field(s), value must be provided")


def test_err_payloadless_variant_with_parens():
    src = SHAPE + "fn main():\n    s = Shape.Empty()\n"
    assert has(messages(src), "variant has no payload, do not write parentheses")


def test_err_pattern_wrong_qualifier():
    src = SHAPE + """enum Other:
    X

fn f(s: Shape):
    match s:
        Other.X:
            pass
        _:
            pass
"""
    assert has(messages(src), "matched value is `Shape`")


def test_print_enum_type_checks():
    src = SHAPE + "fn main():\n    print(Shape.Empty, Shape.Circle(1.0))\n"
    assert messages(src) == []


def test_enum_equality_compares_variant_and_payload():
    src = SHAPE + "fn main():\n    a = Shape.Empty\n    b = Shape.Empty\n    print(a == b)\n"
    assert messages(src) == []


def test_err_enum_name_shadowing_variable():
    src = SHAPE + "fn main():\n    Shape = 1\n"
    assert has(messages(src), "conflicts with a")


def test_err_enum_name_duplicates_struct_name():
    src = "struct A:\n    x: i32\n\nenum A:\n    V\n\nfn main():\n    pass\n"
    assert has(messages(src), "`A` is already defined")


def test_err_enum_name_as_function_name():
    src = SHAPE + "fn Shape():\n    pass\n\nfn main():\n    pass\n"
    assert has(messages(src), "cannot be a function name")


def test_err_method_on_unknown_owner_mentions_enum():
    src = "impl Nope:\n    fn f(self: Nope):\n        pass\n\nfn main():\n    pass\n"
    d = front_end(src)[1][0]
    assert "enum" in d.hint


# ---------------------------------------------------------------- codegen

def test_codegen_scrutinee_evaluated_once():
    c = compile_to_ir(SHAPE + "fn g() -> Shape:\n    return Shape.Empty\n\nfn main():\n    match g():\n        Empty:\n"
                     "            pass\n        _:\n            pass\n")
    assert c.count('@"gg_g"()') == 2  # one definition, one call


def test_codegen_types_in_dependency_order():
    src = """enum Outer:
    Has(Inner)
    No

struct Inner:
    v: i32

fn main():
    o = Outer.Has(Inner{ v: 1 })
    match o:
        Has(i):
            print(i.v)
        No:
            pass
"""
    assert '%"Inner" = type' in compile_to_ir(src)


# ---------------------------------------------------------------- end-to-end


@needs_cc
def test_e2e_shapes_example():
    r = run_example("shapes.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["6", "12", "12", "0"]


@needs_cc
def test_e2e_break_in_match_example():
    r = run_example("break_in_match.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["5"]


@needs_cc
def test_e2e_continue_in_match_inside_while(tmp_path):
    src = """enum E:
    Skip
    Take(i32)

fn mk(i: i32) -> E:
    if i % 2 == 0:
        return E.Skip
    return E.Take(i)

fn main():
    i = 0
    sum = 0
    while i < 10:
        i += 1
        match mk(i):
            Skip:
                continue
            Take(v):
                sum += v
    print(sum)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["25"]


@needs_cc
def test_e2e_nested_enum_struct_array_payloads(tmp_path):
    src = """struct P:
    x: i32
    y: i32

enum Inner:
    A(i32)
    B

enum Outer:
    S(P)
    E(Inner)
    Arr([3]i32)
    Name(str)

fn show(o: Outer):
    match o:
        S(p):
            print("S", p.x + p.y)
        E(i):
            match i:
                A(n):
                    print("A", n)
                B:
                    print("B")
        Arr(a):
            print("Arr", a[0] + a[1] + a[2])
        Name(s):
            print("Name", s)

fn main():
    show(Outer.S(P{ x: 1, y: 2 }))
    show(Outer.E(Inner.A(7)))
    show(Outer.E(Inner.B))
    show(Outer.Arr([1, 2, 3]))
    show(Outer.Name("hi"))
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["S 3", "A 7", "B", "Arr 6", "Name hi"]


@needs_cc
def test_e2e_match_give_and_lend_modify(tmp_path):
    src = """enum E:
    N(i32)
    Z

fn bump(e: lend E):
    match lend e:
        N(v):
            v += 10
        Z:
            pass

fn take(e: consume E) -> i32:
    match consume e:
        N(v):
            v += 1
            return v
        Z:
            return 0

fn main():
    e = E.N(1)
    bump(e)
    print(take(e))
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["12"]


@needs_cc
def test_e2e_enum_method_in_release_mode(tmp_path):
    src = SHAPE + """impl Shape:
    fn area(self: Shape) -> f32:
        match self:
            Circle(r):
                return r * 2.0
            Rect(w, h):
                return w * h
            Empty:
                return 0.0

fn main():
    print(Shape.Rect(2.0, 4.0).area())
"""
    r = run_gg_source(tmp_path, src, release=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["8"]
