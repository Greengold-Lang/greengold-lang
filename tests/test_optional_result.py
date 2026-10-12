"""generic enum, prelude (Optional/Result), shorthand constructors, expected-type inference."""
import pytest

from greengold.cli import compile_to_ir

from .helpers import HAS_CC, messages, run_example, run_gg_source

needs_cc = pytest.mark.skipif(not HAS_CC, reason="gcc/clang not found")


def has(msgs: list[str], text: str) -> bool:
    return any(text in m for m in msgs)


def main_of(body: str, pre: str = "") -> str:
    lines = "".join(f"    {l}\n" if l.strip() else "\n" for l in body.strip("\n").splitlines())
    return pre + "fn main():\n" + lines


# ---------------------------------------------------------------- positive


def test_optional_qualified_ctor_with_type_args():
    assert messages(main_of("x = Optional[i32].Valid(5)\nprint(x.value_or_panic())")) == []


def test_optional_none_with_type_args():
    assert messages(main_of("x = Optional[i32].None\nprint(x.is_none())")) == []


def test_short_ctor_infers_from_payload():
    assert messages(main_of("x = Valid(5)\nprint(x.value_or_panic())")) == []


def test_short_ctor_float_default():
    assert messages(main_of("x = Valid(2.5)\nprint(x.value_or_panic())")) == []


def test_expected_type_in_decl():
    assert messages(main_of("x: Optional[i64] = Valid(5)\ny: Optional[u8] = None\nprint(x.has_value())")) == []


def test_expected_type_in_assignment():
    src = main_of("x: Optional[i32] = None\nx = Valid(3)\nprint(x.value_or_panic())")
    assert messages(src) == []


def test_expected_type_in_call_arg_and_return():
    src = """\
fn pick(o: Optional[i32]) -> Optional[i32]:
    return o

fn none_of() -> Optional[string]:
    return None

fn main():
    print(pick(Valid(4)).value_or_panic())
    print(pick(None).is_none())
    print(none_of().is_none())
"""
    assert messages(src) == []


def test_result_ctors_with_expected_type():
    src = """\
fn f(ok: bool) -> Result[i32, str]:
    if ok:
        return Ok(1)
    return Err("bad")

fn main():
    print(f(true).value_or_panic())
    print(f(false).is_err())
"""
    assert messages(src) == []


def test_match_on_optional_and_result():
    src = """\
fn show(r: Result[i32, str], o: Optional[i32]):
    match r:
        Ok(v):
            print(v)
        Err(e):
            print(e)
    match o:
        Valid(x):
            print(x)
        None:
            pass

fn main():
    show(Ok(1), None)
"""
    assert messages(src) == []


def test_nested_generic_optional_pair():
    src = """\
struct Pair[A, B]:
    first: A
    second: B

fn main():
    o: Optional[Pair[i32, f32]] = Valid(Pair[i32, f32]{ first: 1, second: 2.0 })
    match o:
        Valid(p):
            print(p.first)
        None:
            pass
"""
    assert messages(src) == []


def test_array_payload():
    src = """\
fn main():
    o: Optional[[3]i32] = Valid([1, 2, 3])
    match o:
        Valid(a):
            print(a[1])
        None:
            pass
"""
    assert messages(src) == []


def test_user_generic_enum_and_method():
    src = """\
enum Either[L, R]:
    Left(L)
    Right(R)

impl Either[L, R]:
    fn is_left(self: Either[L, R]) -> bool:
        match self:
            Left(_):
                return true
            Right(_):
                return false

fn main():
    e = Either[i32, f64].Left(3)
    print(e.is_left())
"""
    assert messages(src) == []


def test_generic_fn_over_optional():
    src = """\
fn or_zero[T](o: Optional[T], z: T) -> T:
    return o.value_or(z)

fn main():
    print(or_zero(Optional[i32].None, 5))
"""
    assert messages(src) == []


def test_match_lend_on_generic_enum_payload():
    src = """\
fn main():
    o: Optional[i32] = Valid(1)
    match lend o:
        Valid(v):
            v += 1
        None:
            pass
    print(o.value_or_panic())
"""
    assert messages(src) == []


def test_match_return_and_missing_return_analysis():
    src = """\
fn get(o: Optional[i32]) -> i32:
    match o:
        Valid(v):
            return v
        None:
            return 0

fn main():
    print(get(Valid(2)))
"""
    assert messages(src) == []


def test_move_analysis_in_arm_with_generic_payload():
    src = """\
struct P:
    n: i32

fn eat(p: consume P):
    pass

fn main():
    o: Optional[i32] = Valid(1)
    p = P{ n: 1 }
    match o:
        Valid(_):
            eat(p)
        None:
            eat(p)
"""
    assert messages(src) == []


def test_move_error_after_match_arm():
    src = """\
struct P:
    n: i32

fn eat(p: consume P):
    pass

fn main():
    o: Optional[i32] = Valid(1)
    p = P{ n: 1 }
    match o:
        Valid(_):
            eat(p)
        None:
            pass
    print(p.n)
"""
    assert has(messages(src), "was moved")


# ---------------------------------------------------------------- errors

def test_err_none_without_context():
    assert has(messages(main_of("x = None")), "The type of `x` could not be inferred")


def test_err_err_without_context():
    assert has(messages(main_of('x = Err("e")')), "type could not be inferred")


def test_err_ok_without_error_type():
    assert has(messages(main_of("x = Ok(1)")), "type could not be inferred")


def test_err_qualified_none_without_args():
    assert has(messages(main_of("x = Optional.None")), "type could not be inferred")


def test_err_payload_type_mismatch():
    assert has(messages(main_of("x: Optional[i32] = Valid(true)")), "mismatch")


def test_err_expected_other_enum_family():
    # expected type is Optional but Ok(...) constructs Result; type error is reported because E cannot be inferred
    assert messages(main_of('x: Optional[i32] = Ok(1)'))


def test_err_some_without_payload():
    assert has(messages(main_of("x: Optional[i32] = Valid()")), "expects 1 argument")


def test_err_none_with_parens():
    assert has(messages(main_of("x: Optional[i32] = None(1)")), "has no payload")


def test_err_value_or_panic_or_wrong_type():
    assert has(messages(main_of("x: Optional[i32] = Valid(1)\nprint(x.value_or(true))")), "mismatch")


def test_err_non_exhaustive_match_optional():
    src = main_of("x: Optional[i32] = Valid(1)\nmatch x:\n    Valid(v):\n        print(v)")
    assert has(messages(src), "missing `None`")


def test_err_unknown_variant_on_optional():
    assert has(messages(main_of("x = Optional[i32].Nothing")), "has no variant")


def test_err_wrong_type_arg_count_optional():
    assert has(messages(main_of("x = Optional[i32, i32].None")), "expects 1 type argument")


def test_err_optional_without_args_in_type():
    assert has(messages("fn f(o: Optional):\n    pass\n\nfn main():\n    pass\n"), "generic")


def test_err_reserved_type_names():
    for name in ("Optional", "Result"):
        assert has(messages(f"struct {name}:\n    x: i32\n\nfn main():\n    pass\n"), "reserved"), name
    assert has(messages("enum Optional[T]:\n    A(T)\n\nfn main():\n    pass\n"), "reserved")


def test_err_reserved_function_and_variable_names():
    assert has(messages("fn Valid(x: i32):\n    pass\n\nfn main():\n    pass\n"), "reserved")
    assert has(messages(main_of("None = 5")), "reserved")
    assert has(messages("const Ok: i32 = 5\n\nfn main():\n    pass\n"), "reserved")


def test_err_recursive_generic_enum():
    src = """\
enum LinkedList[T]:
    Cons(T, LinkedList[T])
    Nil

fn f(l: LinkedList[i32]):
    pass

fn main():
    pass
"""
    assert has(messages(src), "enum cannot contain itself by value")


def test_optional_equality_compares_payloads():
    src = main_of("a: Optional[i32] = None\nb: Optional[i32] = None\nprint(a == b)")
    assert messages(src) == []


def test_print_optional_type_checks():
    assert messages(main_of("a: Optional[i32] = None\nprint(a)")) == []


def test_err_method_on_unknown_optional_method():
    assert has(messages(main_of("a: Optional[i32] = None\nprint(a.map())")), "map")


# ---------------------------------------------------------------- IR output

def test_c_names_for_optional_instances():
    c = compile_to_ir(main_of("x: Optional[i32] = Valid(1)\nprint(x.value_or_panic())"))
    assert "Optional_i32" in c and "Optional_i32_value_or_panic" in c
    assert "Optional_i32_has_value" not in c  # unused method is not emitted


def test_prelude_unused_not_emitted():
    c = compile_to_ir("fn main():\n    pass\n")
    assert "Optional" not in c and "Result" not in c


# ---------------------------------------------------------------- end-to-end


@needs_cc
def test_e2e_optional_example():
    r = run_example("optional.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["2", "7"]


@needs_cc
def test_e2e_result_example():
    r = run_example("result.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().split("\n") == ["7", "not a digit"]


@needs_cc
def test_e2e_value_or_panic_fail_debug():
    r = run_example("value_or_panic_fail.gg")
    assert r.returncode == 101
    assert "value_or_panic: no value (None)" in r.stderr


@needs_cc
def test_e2e_match_lend_modifies_optional(tmp_path):
    src = """\
fn main():
    o: Optional[i32] = Valid(1)
    match lend o:
        Valid(v):
            v += 41
        None:
            pass
    print(o.value_or_panic())
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "42"


@needs_cc
def test_e2e_nested_optional_pair(tmp_path):
    src = """\
struct Pair[A, B]:
    first: A
    second: B

fn main():
    o: Optional[Pair[i32, f32]] = Valid(Pair[i32, f32]{ first: 9, second: 1.5 })
    print(o.value_or_panic().first)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "9"


@needs_cc
def test_e2e_array_payload(tmp_path):
    src = "fn main():\n    o: Optional[[3]i32] = Valid([4, 5, 6])\n    print(o.value_or_panic()[2])\n"
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "6"


@needs_cc
def test_e2e_result_value_or_panic_fail(tmp_path):
    r = run_gg_source(tmp_path, 'fn main():\n    r: Result[i32, str] = Err("x")\n    print(r.value_or_panic())\n')
    assert r.returncode == 101
    assert "value_or_panic" in r.stderr
