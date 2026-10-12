"""generic structs and functions (monomorphization)."""
import pytest

from greengold.ast_nodes import Call, FuncDecl, IndexAccess, StructDecl, StructLit, TypeApp
from greengold.cli import compile_to_ir
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse

from .helpers import HAS_CC, front_end, messages, run_example, run_gg_source

needs_cc = pytest.mark.skipif(not HAS_CC, reason="gcc/clang not found")

PAIR = """\
struct Pair[A, B]:
    first: A
    second: B

"""

MAX = """\
fn max[T: Ord](a: T, b: T) -> T:
    if a > b:
        return a
    return b

"""


def has(msgs: list[str], text: str) -> bool:
    return any(text in m for m in msgs)


def parse_src(src: str):
    diags = DiagnosticBag()
    prog = parse(tokenize(src, diags), diags)
    return prog, [d.message for d in diags.items]


def full(src: str):
    """Type checking error diagnostics (as objects)."""
    return front_end(src)[1]


# ---------------------------------------------------------------- parser

def test_parse_generic_struct():
    prog, errs = parse_src(PAIR + "fn main():\n    pass\n")
    assert not errs
    d = prog.decls[0]
    assert isinstance(d, StructDecl) and d.type_params == ["A", "B"]


def test_parse_generic_fn_and_method():
    prog, errs = parse_src(MAX + "impl Pair[A, B]:\n    fn swap(self: Pair[A, B]) -> Pair[B, A]:\n        pass\n")
    assert not errs
    f, m = prog.decls
    assert isinstance(f, FuncDecl) and f.type_params == ["T"] and f.owner is None
    assert m.owner == "Pair" and m.owner_params == ["A", "B"] and m.type_params == []


def test_parse_generic_type_ref():
    prog, errs = parse_src("fn f(p: Pair[i32, [3]f64]):\n    pass\n")
    assert not errs
    ref = prog.decls[0].params[0].type_ref
    assert ref.base == "Pair" and [a.name for a in ref.args] == ["i32", "[3]f64"]


def test_parse_explicit_call_and_struct_lit():
    prog, errs = parse_src("fn main():\n    a = max[i64](5, 2)\n    b = Pair[i32, f64]{ first: 1, second: 2.0 }\n")
    assert not errs
    body = prog.decls[0].body
    assert isinstance(body[0].value, Call) and [t.name for t in body[0].value.type_args] == ["i64"]
    assert isinstance(body[1].value, StructLit) and len(body[1].value.type_args) == 2


def test_parse_index_stays_index():
    prog, errs = parse_src("fn main():\n    a = [1, 2, 3]\n    x = a[1]\n    y = a[1..3]\n")
    assert not errs
    assert isinstance(prog.decls[0].body[1].value, IndexAccess)


def test_parse_type_application_expr():
    prog, errs = parse_src("fn main():\n    x = Optional[i32].None\n")
    assert not errs


def test_parse_empty_type_args_error():
    _, errs = parse_src("fn f(p: Pair[]):\n    pass\n")
    assert has(errs, "empty")


def test_parse_method_cannot_have_own_type_params():
    _, errs = parse_src("impl Pair[A]:\n    fn f[B](self: Pair[A]):\n        pass\n")
    assert has(errs, "cannot have their own")


# ---------------------------------------------------------------- positive type checking

def test_generic_struct_ok():
    assert messages(PAIR + "fn main():\n    p = Pair[i32, f64]{ first: 1, second: 2.5 }\n    print(p.first)\n") == []


def test_nested_generic_type():
    src = PAIR + """\
struct Holder[T]:
    inner: T

fn main():
    b = Holder[Pair[i32, f32]]{ inner: Pair[i32, f32]{ first: 1, second: 2.0 } }
    print(b.inner.first)
"""
    assert messages(src) == []


def test_generic_fn_inference_ok():
    assert messages(MAX + "fn main():\n    print(max(3, 9))\n    print(max(1.5, 0.5))\n") == []


def test_inference_const_defaults():
    # non-constant argument determines type; constants conform to it
    src = MAX + "fn main():\n    x: i64 = 4\n    print(max(x, 9))\n"
    assert messages(src) == []


def test_generic_method_ok():
    src = PAIR + """\
impl Pair[A, B]:
    fn swap(self: Pair[A, B]) -> Pair[B, A]:
        return Pair[B, A]{ first: self.second, second: self.first }

fn main():
    p = Pair[i32, f64]{ first: 1, second: 2.5 }
    q = p.swap()
    print(q.first)
"""
    assert messages(src) == []


def test_generic_with_array_param():
    src = """\
fn first[T](xs: []T) -> T:
    return xs[0]

fn main():
    a = [4, 5, 6]
    print(first(a))
"""
    assert messages(src) == []


def test_generic_give_copyable_ok():
    src = """\
fn id[T](x: consume T) -> T:
    return x

fn main():
    n = 5
    print(id(n))
"""
    assert messages(src) == []


def test_generic_give_copy_does_not_move():
    src = """\
fn take[T](x: consume T):
    pass

fn main():
    n = 5
    take(n)
    print(n)
"""
    assert messages(src) == []


def test_generic_give_struct_moves():
    src = """\
struct Player:
    name: str

fn take[T](x: consume T):
    pass

fn main():
    p = Player{ name: "a" }
    take(p)
    print(p.name)
"""
    assert has(messages(src), "was moved") or has(messages(src), "moved")


def test_non_generic_give_primitive_still_error():
    src = "fn take(x: consume i32):\n    pass\n\nfn main():\n    n = 5\n    take(n)\n"
    assert has(messages(src), "is copied")


# ---------------------------------------------------------------- error messages

def test_err_conflicting_inference():
    assert has(messages(MAX + "fn main():\n    a: i32 = 1\n    b: f64 = 2.0\n    print(max(a, b))\n"),
               "T was inferred as both i32 and f64")


def test_err_wrong_type_arg_count():
    assert has(messages(PAIR + "fn main():\n    p = Pair[i32]{ first: 1 }\n"), "expects 2 type argument")


def test_err_generic_type_without_args():
    assert has(messages(PAIR + "fn f(p: Pair):\n    pass\n\nfn main():\n    pass\n"), "generic")


def test_err_struct_lit_without_type_args():
    # The fields show every type parameter, so the literal is a `Pair[i32, i32]`.
    assert messages(PAIR + "fn main():\n    p = Pair{ first: 1, second: 2 }\n") == []
    tagged = "struct Tagged[T]:\n    n: i32\n\n"
    assert has(messages(tagged + "fn main():\n    t = Tagged{ n: 1 }\n"), "explicitly")


def test_err_type_args_on_non_generic_type():
    src = "struct P:\n    x: i32\n\nfn f(p: P[i32]):\n    pass\n\nfn main():\n    pass\n"
    assert has(messages(src), "is not a generic type")


def test_err_type_args_on_non_generic_fn():
    src = "fn f(x: i32):\n    pass\n\nfn main():\n    f[i32](1)\n"
    assert has(messages(src), "generic")


def test_err_partial_type_args_fn():
    src = "fn two[A, B](a: A, b: B):\n    pass\n\nfn main():\n    two[i32](1, 2)\n"
    assert has(messages(src), "partial type argument")


def test_err_cannot_infer():
    src = "fn zero[T]() -> T:\n    return T(0)\n\nfn main():\n    x = zero()\n"
    assert has(messages(src), "type could not be inferred")


def test_err_duplicate_type_param():
    assert has(messages("struct P[T, T]:\n    a: T\n\nfn main():\n    pass\n"), "written twice")


def test_err_type_param_clashes_with_type():
    src = "struct Q:\n    x: i32\n\nstruct P[Q]:\n    a: Q\n\nfn main():\n    pass\n"
    assert has(messages(src), "conflicts with")


def test_err_generic_main():
    assert has(messages("fn main[T]():\n    pass\n"), "`main` cannot be generic")


def test_err_slice_type_arg():
    src = PAIR + "fn f(p: Pair[[]i32, i32]):\n    pass\n\nfn main():\n    pass\n"
    assert has(messages(src), "Slice")


def test_err_method_on_non_generic_with_params():
    src = "struct P:\n    x: i32\n\nimpl P[T]:\n    fn f(self: P):\n        pass\n\nfn main():\n    pass\n"
    assert has(messages(src), "is not a generic type")


def test_err_method_missing_params_for_generic_owner():
    src = PAIR + "impl Pair:\n    fn f(self: Pair[i32, i32]):\n        pass\n\nfn main():\n    pass\n"
    assert has(messages(src), "is a generic type")


def test_err_wrong_arg_count_generic_call():
    assert has(messages(MAX + "fn main():\n    print(max(1))\n"), "expects 2 argument")


def test_err_type_mismatch_after_explicit_args():
    assert has(messages(MAX + "fn main():\n    print(max[i64](1.5, 2))\n"), "mismatch")


def test_err_unknown_method_on_generic_instance():
    src = PAIR + "fn main():\n    p = Pair[i32, i32]{ first: 1, second: 2 }\n    p.nope()\n"
    assert has(messages(src), "nope")


def test_err_recursive_generic_struct():
    src = "struct Node[T]:\n    value: T\n    next: Node[T]\n\nfn f(n: Node[i32]):\n    pass\n\nfn main():\n    pass\n"
    assert has(messages(src), "infinite size") or has(messages(src), "contains itself")


# ---------------------------------------------------------------- instantiation-time checking

def test_instantiation_error_has_note_and_dedupes():
    src = """\
fn bad[T](a: T, b: T) -> T:
    if a > b:
        return a
    return b

struct Player:
    hp: i32

fn main():
    p = Player{ hp: 1 }
    q = Player{ hp: 2 }
    x = bad(p, q)
    y = bad(p, q)
"""
    diags = full(src)
    assert diags, "error expected"
    errs = [d for d in diags if "Player" in d.message or "compare" in d.message or ">" in d.message]

    assert errs
    # identical error on the same line from two calls is reported only once
    keys = [(d.line, d.col, d.message) for d in diags]
    assert len(keys) == len(set(keys))
    assert any("instantiated with T = Player" in n.text for d in diags for n in d.notes)


def test_instantiation_error_bool_plus_with_note():
    src = """\
fn add[T](a: T, b: T) -> T:
    return a + b

fn main():
    x = add(true, false)
"""
    diags = full(src)
    assert diags
    assert any("instantiated with T = bool" in n.text for d in diags for n in d.notes)


def test_instantiation_depth_limit():
    src = """\
struct W[T]:
    v: T

fn deep[T](x: T):
    deep[W[T]](W[T]{ v: x })

fn main():
    deep(1)
"""
    assert has(messages(src), "infinite recursive instantiation")


def test_instance_cache_one_function():
    c = compile_to_ir(MAX + "fn main():\n    print(max(1, 2))\n    print(max(3, 4))\n")
    assert c.count('@"gg_max_i32"(') == 3 and c.count('define internal i32 @"gg_max_i32"(') == 1


def test_unused_generic_not_emitted():
    c = compile_to_ir(MAX + PAIR + "fn main():\n    pass\n")
    assert "max" not in c and "Pair" not in c


def test_instance_names():
    src = PAIR + MAX + """\
fn main():
    p = Pair[i32, f64]{ first: 1, second: 2.0 }
    print(max[i64](5, 2))
    print(p.first)
"""
    c = compile_to_ir(src)
    assert "Pair_i32__f64_" in c and '@"gg_max_i64"' in c


def test_t_cast_in_generic_body():
    src = """\
fn twice[T: Num](x: T) -> T:
    return x + T(1)

fn main():
    print(twice(41))
"""
    assert messages(src) == []


def test_t_cast_non_numeric_error():
    src = """\
struct P:
    a: i32

fn conv[T](x: i32) -> i32:
    y = T(x)
    return 0

fn main():
    print(conv[P](1))
"""
    assert has(messages(src), "is not a numeric type")


# ---------------------------------------------------------------- end-to-end

@needs_cc
def test_e2e_generics_example():
    r = run_example("generics.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n")[:4] == ["2.5 1", "9", "1.5", "5"]


@needs_cc
def test_e2e_generic_struct_method(tmp_path):
    src = PAIR + """\
impl Pair[A, B]:
    fn sum(self: Pair[A, B]) -> A:
        return self.first

fn main():
    p = Pair[i64, bool]{ first: 40, second: true }
    print(p.sum() + 2)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "42"


@needs_cc
def test_e2e_nested_generic(tmp_path):
    src = PAIR + """\
struct Holder[T]:
    inner: T

fn main():
    b = Holder[Pair[i32, f32]]{ inner: Pair[i32, f32]{ first: 7, second: 1.5 } }
    print(b.inner.first)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "7"


@needs_cc
def test_e2e_t_cast(tmp_path):
    src = "fn twice[T: Num](x: T) -> T:\n    return x + T(1)\n\nfn main():\n    print(twice(41))\n    print(twice(1.5))\n"
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["42", "2.5"]
