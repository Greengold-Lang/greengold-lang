"""tuples, type aliases, impl blocks, `if let` / `while let`, operator overloading."""
from tests.helpers import front_end, messages, run_gg_source, run_example


def ok(src: str) -> None:
    prog, diags = front_end(src)
    assert not diags, [d.message for d in diags]


def test_example_runs():
    r = run_example("phase1.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n")[:3] == ["3 2", "1 2.5 true", "7 1.5"]
    assert "pop 2" in r.stdout and "pop 1" in r.stdout


def test_tuple_type_and_literal():
    ok("""
fn swap(p: (i32, f64)) -> (f64, i32):
    return (p.1, p.0)

fn main():
    x = swap((1, 2.0))
    print(x.0, x.1)
""")


def test_tuple_destructure_and_wildcard():
    ok("""
fn main():
    a, _, c = (1, 2, 3)
    d, e = (4, 5)
    d += a + c
    print(d, e)
""")


def test_tuple_mismatch_reports_error():
    msgs = messages("""
fn f() -> (i32, i32):
    return (1, 2.5)

fn main():
    x = f()
""")
    assert any("Type mismatch" in m for m in msgs)


def test_tuple_size_limit():
    msgs = messages("""
fn main():
    t = (1, 2, 3, 4, 5, 6, 7)
""")
    assert any("Tuples must have" in m for m in msgs)


def test_type_alias():
    ok("""
type Id = u32
type Ids = List[Id]
type Grid = [4]i32

fn main():
    ids = Ids()
    ids.push(Id(3))
    g: Grid = [1, 2, 3, 4]
    print(ids.len, g[2])
""")


def test_type_alias_cycle_is_error():
    msgs = messages("""
type A = B
type B = A

fn main():
    x: A = 1
""")
    assert msgs


def test_impl_block_and_self_shorthand():
    ok("""
struct P:
    x: i32

impl P:
    fn double(self) -> i32:
        return self.x * 2

    fn me(self: Self) -> Self:
        return self

fn main():
    p = P{ x: 2 }
    print(p.me().double())
""")


def test_impl_generic():
    ok("""
struct Box2[T]:
    v: T

impl Box2[T]:
    fn get(self) -> T:
        return self.v

fn main():
    b = Box2[i32]{ v: 5 }
    print(b.get())
""")


def test_if_let_without_else_and_with_else():
    ok("""
fn main():
    o: Optional[i32] = Valid(3)
    if let Valid(x) = o:
        print(x)
    if let None = o:
        print("none")
    else:
        print("some")
""")


def test_while_let_runs(tmp_path):
    r = run_gg_source(tmp_path, """
fn main():
    v = List[i32]()
    v.push(1)
    v.push(2)
    v.push(3)
    sum = 0
    while let Valid(x) = v.pop():
        sum += x
    print(sum)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "6"


def test_operator_overloading_runs(tmp_path):
    r = run_gg_source(tmp_path, """
struct V:
    x: i32

impl V:
    fn add(self, o: V) -> V:
        return V{ x: self.x + o.x }

    fn eq(self, o: V) -> bool:
        return self.x == o.x

    fn neg(self) -> V:
        return V{ x: -self.x }

fn main():
    a = V{ x: 2 }
    b = a + a
    print(b.x, (-b).x, a == b, a != b)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "4 -4 false true"


def test_operator_without_method_is_error():
    msgs = messages("""
struct V:
    x: i32

fn main():
    a = V{ x: 1 }
    b = a * a
""")
    assert any("does not support operator `*`" in m for m in msgs)


def test_comparison_operator_must_return_bool():
    msgs = messages("""
struct V:
    x: i32

impl V:
    fn lt(self: V, o: V) -> i32:
        return 1

fn main():
    a = V{ x: 1 }
    print(a < a)
""")
    assert any("must return `bool`" in m for m in msgs)
