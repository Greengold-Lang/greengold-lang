"""function pointers + lambdas, user iterators in `for`, static methods, `?` error conversion,
checked / saturating / wrapping integer arithmetic."""
import pytest

from tests.helpers import HAS_CC, front_end, messages, run_example, run_gg_source


def ok(src: str) -> None:
    _, diags = front_end(src)
    assert not diags, [d.message for d in diags]


def test_fn_pointer_example():
    r = run_example("fn_pointers.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["7", "12", "21", "3", "clicked", "7", "lambda", "ok"]


def test_fn_pointer_type_mismatch():
    msgs = messages("""
fn f(a: i32) -> i32:
    return a

fn main():
    g: fn(i64) -> i64 = f
""")
    assert any("Type mismatch" in m for m in msgs)


def test_fn_value_with_lend_param_rejected():
    msgs = messages("""
fn bump(a: lend i32):
    a += 1

fn main():
    g = bump
""")
    assert any("cannot be used as a function value" in m for m in msgs)


def test_lambda_can_capture():
    msgs = messages("""
fn main():
    k = 3
    f = fn(x: i32) -> i32 => x + k
    print(f(1))
""")
    assert msgs == []  # closures: see tests/test_closures.py


def test_fn_pointer_wrong_arity():
    msgs = messages("""
fn main():
    f = fn(x: i32) -> i32 => x
    print(f(1, 2))
""")
    assert any("expects 1 argument" in m for m in msgs)


def test_iterator_for_loop():
    r = run_example("iterator.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["1", "2", "3", "y", "0", "y", "2"]


def test_iterator_requires_mutable_variable():
    msgs = messages("""
struct C:
    n: i32

impl C:
    fn next(self: lend C) -> Optional[i32]:
        return None

fn main():
    fixed c = C{ n: 0 }
    for x in c:
        print(x)
""")
    assert msgs


def test_static_method(tmp_path):
    r = run_gg_source(tmp_path, """
struct V:
    x: i32

impl V:
    fn new(x: i32) -> V:
        return V{ x: x }

    fn origin() -> V:
        return V.new(0)

    fn get(self) -> i32:
        return self.x

fn main():
    print(V.new(5).get(), V.origin().get())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "5 0"


def test_try_converts_error_with_from():
    r = run_example("try_from.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n")[:2] == ["ok 11", "parse error -3"]


def test_try_without_from_is_error():
    msgs = messages("""
fn a() -> Result[i32, i32]:
    return Ok(1)

fn b() -> Result[i32, bool]:
    x = a()?
    return Ok(x)

fn main():
    pass
""")
    assert any("error types do not match" in m for m in msgs)


def test_integer_ops_example():
    r = run_example("int_ops.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n") == [
        "-1", "123", "2147483647 -2147483648", "255 0", "4 0",
        "9223372036854775807 -9223372036854775808 18446744073709551615 -9223372036854775808", "true", ""]


def test_integer_ops_release_mode():
    r = run_example("int_ops.gg", release=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("-1\n123\n")


def test_max_value_requires_integer_type():
    msgs = messages("""
fn main():
    x = max_value[f64]()
""")
    assert any("requires an integer type" in m for m in msgs)


