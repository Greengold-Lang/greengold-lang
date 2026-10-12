"""Closures: lambdas that capture variables of the enclosing function."""
from greengold.cli import compile_to_ir
from tests.helpers import messages, run_built

PROGRAM = """\
fn apply(f: fn(i32) -> i32, x: i32) -> i32:
    return f(x)

fn apply2(f: fn(i32) -> i32, x: i32) -> i32:
    return apply(f, apply(f, x))

fn map(xs: List[i32], f: fn(i32) -> i32) -> List[i32]:
    out = List[i32]()
    for x in xs:
        out.push(f(x))
    return out

fn count_if(xs: List[i32], keep: fn(i32) -> bool) -> i32:
    n = 0
    for x in xs:
        if keep(x):
            n += 1
    return n

fn twice(x: i32) -> i32:
    return x * 2

struct C:
    base: i32

impl C:
    fn shifted(self: Self, x: i32) -> i32:
        f = fn(v: i32) -> i32 => v + self.base
        return f(x)

fn main():
    k = 3
    add_k = fn(x: i32) -> i32 => x + k
    print(add_k(1), apply(add_k, 10), apply(twice, 10), apply2(add_k, 0))
    xs = List[i32]()
    for i in 0..5:
        xs.push(i)
    ys = map(xs, fn(x: i32) -> i32 => x * k)
    print(ys.len, ys[4])
    limit = 2
    print(count_if(xs, fn(x: i32) -> bool => x > limit))
    has = fn(v: i32) -> bool => xs.len > usize(v)
    print(has(4), has(5))
    g = fn(x: i32) -> i32 => add_k(x) + 1
    print(g(1), C{ base: 5 }.shifted(1))
"""


def test_closures_run_and_do_not_leak(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["4 13 20 6", "5 12", "2", "true false", "5 6"]
    assert "leak" not in r.stderr.lower()


def test_closure_argument_is_monomorphized():
    src = ("fn apply(f: fn(i32) -> i32, x: i32) -> i32:\n    return f(x)\n\n"
           "fn main():\n    k = 3\n    print(apply(fn(x: i32) -> i32 => x + k, 1))\n")
    ir = compile_to_ir(src)
    head, body = ir.split('define internal i32 @"gg_apply___closure', 1)
    body = body.split("\n}\n", 1)[0]
    assert 'call i32 @"gg___lambda_' in body  # a direct call, not through a function pointer


def test_captured_heap_value_is_protected_while_closure_is_live():
    src = "fn main():\n    v = List[i32]()\n    f = fn(i: i32) -> usize => v.len\n    v.push(1)\n    print(f(0))\n"
    assert any("`f` is still tied to it" in m for m in messages(src))
    ok = "fn main():\n    v = List[i32]()\n    f = fn(i: i32) -> usize => v.len\n    print(f(0))\n    v.push(1)\n"
    assert messages(ok) == []


def test_closure_that_changes_a_capture_borrows_it_as_lend(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn for_each(xs: List[i32], f: fn(i32)):
    for x in xs:
        f(x)

fn keep_even(x: i32, into: lend List[i32]):
    if x % 2 == 0:
        into.push(x)

fn main():
    xs = List[i32]()
    for i in 0..4:
        xs.push(i)
    evens = List[i32]()
    for_each(xs, fn(x: i32) => keep_even(x, evens))
    out = List[i32]()
    collect = fn(x: i32) => out.push(x * 10)
    collect(1)
    collect(2)
    print(evens.len, out.len, out[1])
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["2", "2", "20"]
    assert "LEAK" not in r.stderr


def test_changing_closure_is_exclusive():
    live = "fn main():\n    out = List[i32]()\n    c = fn(x: i32) => out.push(x)\n    print(out.len)\n    c(1)\n"
    assert any("borrowed as `lend` by `c`" in m for m in messages(live))
    two = ("fn main():\n    out = List[i32]()\n    a = fn(x: i32) => out.push(x)\n"
           "    b = fn(x: i32) => out.push(x)\n    a(1)\n    b(2)\n")
    assert any("borrowed as `lend` by `a`" in m for m in messages(two))
    immutable = "fn main():\n    fixed out = List[i32]()\n    c = fn(x: i32) => out.push(x)\n    c(1)\n"
    assert any("cannot be `lend`ed" in m for m in messages(immutable))


def test_closure_cannot_be_returned_as_fn_value():
    src = ("fn mk(k: i32) -> fn(i32) -> i32:\n    return fn(x: i32) -> i32 => x + k\n\n"
           "fn main():\n    f = mk(1)\n    print(f(2))\n")
    assert any("cannot be stored or returned as a `fn(...)` value" in m for m in messages(src))


def test_closure_signature_must_match_parameter():
    src = ("fn apply(f: fn(i32) -> i32, x: i32) -> i32:\n    return f(x)\n\n"
           "fn main():\n    k = 1\n    print(apply(fn(x: i64) -> i64 => x + i64(k), 1))\n")
    assert any("does not match parameter" in m for m in messages(src))


def test_capture_free_lambda_is_still_a_function_pointer():
    src = ("fn apply(f: fn(i32) -> i32, x: i32) -> i32:\n    return f(x)\n\n"
           "fn main():\n    inc = fn(x: i32) -> i32 => x + 1\n    print(apply(inc, 1))\n")
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2"
    assert "__closure" not in compile_to_ir(src)


def test_closure_passed_to_generic_function():
    src = """\
fn map[T, U](xs: List[T], f: fn(T) -> U) -> List[U]:
    out = List[U]()
    for x in xs:
        out.push(f(x))
    return out

fn neg(x: i32) -> i32:
    return -x

fn main():
    k = 2
    xs = List[i32]()
    xs.push(1)
    xs.push(5)
    ys = map(xs, fn(x: i32) -> i64 => i64(x * k))
    zs = map(xs, fn(x: i32) -> bool => x > k)
    print(ys[1], zs[0], zs[1], map(xs, neg)[0])
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["10", "false", "true", "-1"]


def test_closure_passed_to_method():
    src = """\
struct Nums:
    xs: List[i32]

impl Nums:
    fn count_if(self: Self, keep: fn(i32) -> bool) -> i32:
        n = 0
        for x in self.xs:
            if keep(x):
                n += 1
        return n

fn main():
    s = Nums{ xs: List[i32]() }
    s.xs.push(5)
    s.xs.push(1)
    lim = 3
    print(s.count_if(fn(x: i32) -> bool => x > lim))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1"
