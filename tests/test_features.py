"""Features: `feature`, `T: Bound`, builtin Num/Int/Float/Ord/Eq."""
import pytest

from .helpers import HAS_CC, messages
from .test_heap import ok

needs_cc = pytest.mark.skipif(not HAS_CC, reason="C compiler not found")

SHAPES = """
feature Shape:
    fn area(self: Self) -> f64
    fn scale(self: lend Self, k: f64)

struct Circle:
    r: f64

struct Square:
    s: f64

impl Circle:
    fn area(self: Circle) -> f64:
        return 3.0 * self.r * self.r

    fn scale(self: lend Circle, k: f64):
        self.r *= k

impl Square:
    fn area(self: Square) -> f64:
        return self.s * self.s

    fn scale(self: lend Square, k: f64):
        self.s *= k

fn total[T: Shape](a: T, b: T) -> f64:
    return a.area() + b.area()

fn grow[T: Shape](x: lend T):
    x.scale(2.0)
"""


@needs_cc
def test_feature_bound_static_dispatch(tmp_path):
    src = SHAPES + """
fn main():
    c = Circle{ r: 1.0 }
    d = Circle{ r: 2.0 }
    print(total(c, d))
    s = Square{ s: 3.0 }
    grow(s)
    print(s.area())
    grow(c)
    print(c.area())
"""
    ok(tmp_path, src, ["15", "36", "12"])


def test_missing_method_is_reported_at_call():
    src = SHAPES + """
struct Blob:
    n: i32

fn main():
    b = Blob{ n: 1 }
    print(total(b, b))
"""
    errs = messages(src)
    assert any("Shape" in m and "is not defined" in m for m in errs), errs


def test_signature_mismatch_is_reported():
    src = SHAPES + """
struct Tri:
    h: f64

impl Tri:
    fn area(self: Tri) -> i32:
        return 1

    fn scale(self: Tri, k: f64):
        pass

fn main():
    t = Tri{ h: 1.0 }
    print(total(t, t))
"""
    errs = " ".join(messages(src))
    assert "must return" in errs and "mode" in errs


def test_builtin_bounds():
    good = "fn big[T: Ord](a: T, b: T) -> T:\n    if a > b:\n        return a\n    return b\n\nfn main():\n    print(big(1, 2))\n"
    assert messages(good) == []
    bad = "fn big[T: Ord](a: T, b: T) -> T:\n    return a\n\nfn main():\n    print(big(true, false))\n"
    assert any("Ord" in m for m in messages(bad))
    assert any("Float" in m for m in messages(
        "fn half[T: Float](a: T) -> T:\n    return a\n\nfn main():\n    print(half(3))\n"))


def test_struct_bounds_and_unknown_feature():
    src = "struct Wrap[T: Num]:\n    v: T\n\nfn main():\n    w = Wrap[string]{ v: \"x\" }\n"
    assert any("Num" in m for m in messages(src))
    assert any(("Unknown feature" in m or "Unknown feature" in m) for m in messages("fn f[T: Nope](a: T):\n    pass\n\nfn main():\n    pass\n"))
    assert any("reserved" in m or "already defined" in m for m in messages("feature Ord:\n    fn f(self: Self)\n\nfn main():\n    pass\n"))


@needs_cc
def test_feature_default_body_execution(tmp_path):
    src = """
feature Shape:
    fn area(self: Self) -> f64
    fn scale(self: lend Self, k: f64)
    fn double_area(self: Self) -> f64:
        return 2.0 * self.area()
    fn grow_twice(self: lend Self):
        self.scale(2.0)

struct Circle:
    r: f64

struct Square:
    s: f64

impl Circle:
    fn area(self: Circle) -> f64:
        return 3.0 * self.r * self.r

    fn scale(self: lend Circle, k: f64):
        self.r *= k

impl Square:
    fn area(self: Square) -> f64:
        return self.s * self.s

    fn scale(self: lend Square, k: f64):
        self.s *= k

    fn double_area(self: Square) -> f64:
        return 999.0

fn call_double[T: Shape](x: T) -> f64:
    return x.double_area()

fn main():
    c = Circle{ r: 2.0 }
    print(c.double_area())
    print(call_double(c))
    c.grow_twice()
    print(c.area())
    s = Square{ s: 3.0 }
    print(s.double_area())
    print(call_double(s))
"""
    ok(tmp_path, src, ["24", "24", "48", "999", "999"])


def test_feature_missing_required_function_disables_feature():
    # If a function without default body is missing, the feature is absent ("the feature is ignored").
    src = """
feature Shape:
    fn area(self: Self) -> f64
    fn scale(self: lend Self, k: f64)
    fn double_area(self: Self) -> f64:
        return 2.0 * self.area()

struct Partial:
    r: f64

impl Partial:
    fn area(self: Partial) -> f64:
        return self.r

fn call_bound[T: Shape](x: T):
    pass

fn main():
    p = Partial{ r: 1.0 }
    call_bound(p)
"""
    errs = messages(src)
    assert any("Shape" in m and "scale" in m for m in errs), errs

    # Direct call to default method on Partial should also fail since Partial doesn't have the feature
    src_direct = """
feature Shape:
    fn area(self: Self) -> f64
    fn scale(self: lend Self, k: f64)
    fn double_area(self: Self) -> f64:
        return 2.0 * self.area()

struct Partial:
    r: f64

impl Partial:
    fn area(self: Partial) -> f64:
        return self.r

fn main():
    p = Partial{ r: 1.0 }
    print(p.double_area())
"""
    errs_direct = messages(src_direct)
    assert any("no method named" in m and "double_area" in m for m in errs_direct), errs_direct


@needs_cc
def test_feature_chained_default_methods(tmp_path):
    src = """
feature MathObj:
    fn val(self: Self) -> i32
    fn dbl(self: Self) -> i32:
        return self.val() * 2
    fn quad(self: Self) -> i32:
        return self.dbl() * 2

struct Num:
    n: i32

impl Num:
    fn val(self: Num) -> i32:
        return self.n

fn main():
    x = Num{ n: 5 }
    print(x.val())
    print(x.dbl())
    print(x.quad())
"""
    ok(tmp_path, src, ["5", "10", "20"])


def test_feature_conflicting_defaults():
    src = """
feature A:
    fn f(self: Self) -> i32:
        return 1

feature B:
    fn f(self: Self) -> i32:
        return 2

struct S:
    x: i32

fn main():
    s = S{ x: 1 }
"""
    errs = messages(src)
    assert any("Conflicting default implementations" in m and "f" in m for m in errs), errs


def test_feature_multiple_required_methods_missing_one():
    src = """
feature MultiReq:
    fn f1(self: Self) -> i32
    fn f2(self: Self) -> i32
    fn f3(self: Self) -> i32
    fn sum(self: Self) -> i32:
        return self.f1() + self.f2() + self.f3()

struct OnlyTwo:
    a: i32
    b: i32

impl OnlyTwo:
    fn f1(self: OnlyTwo) -> i32:
        return self.a
    fn f2(self: OnlyTwo) -> i32:
        return self.b

fn test_bound[T: MultiReq](x: T):
    pass

fn main():
    o = OnlyTwo{ a: 1, b: 2 }
    test_bound(o)
"""
    errs = messages(src)
    assert any("MultiReq" in m and "f3" in m for m in errs), errs


@needs_cc
def test_feature_multiple_required_methods_all_implemented(tmp_path):
    src = """
feature MultiReq:
    fn f1(self: Self) -> i32
    fn f2(self: Self) -> i32
    fn f3(self: Self) -> i32
    fn sum(self: Self) -> i32:
        return self.f1() + self.f2() + self.f3()

struct AllThree:
    a: i32
    b: i32
    c: i32

impl AllThree:
    fn f1(self: AllThree) -> i32:
        return self.a
    fn f2(self: AllThree) -> i32:
        return self.b
    fn f3(self: AllThree) -> i32:
        return self.c

fn compute[T: MultiReq](x: T) -> i32:
    return x.sum()

fn main():
    x = AllThree{ a: 10, b: 20, c: 30 }
    print(x.sum())
    print(compute(x))
"""
    ok(tmp_path, src, ["60", "60"])


@needs_cc
def test_feature_default_method_with_self_param(tmp_path):
    src = """
feature Equatable:
    fn is_equal(self: Self, other: Self) -> bool
    fn not_equal(self: Self, other: Self) -> bool:
        return not self.is_equal(other)

struct Point:
    x: i32
    y: i32

impl Point:
    fn is_equal(self: Point, other: Point) -> bool:
        return self.x == other.x and self.y == other.y

fn main():
    p1 = Point{ x: 1, y: 2 }
    p2 = Point{ x: 1, y: 2 }
    p3 = Point{ x: 2, y: 3 }
    print(p1.not_equal(p2))
    print(p1.not_equal(p3))
"""
    ok(tmp_path, src, ["false", "true"])


@needs_cc
def test_generic_struct_feature_default_method(tmp_path):
    src = """
feature Container:
    fn count(self: Self) -> i32
    fn is_empty(self: Self) -> bool:
        return self.count() == 0

struct Wrapper[T]:
    elem: T
    size: i32

impl Wrapper[T]:
    fn count(self: Wrapper[T]) -> i32:
        return self.size

fn main():
    w = Wrapper[i32]{ elem: 42, size: 0 }
    print(w.is_empty())
    w2 = Wrapper[i32]{ elem: 100, size: 5 }
    print(w2.is_empty())
"""
    ok(tmp_path, src, ["true", "false"])


from .test_llvm import needs_linker, run_src


@needs_linker
def test_feature_default_method_llvm(tmp_path):
    src = """
feature Greeter:
    fn name(self: Self) -> i32
    fn greet(self: Self) -> i32:
        return self.name() * 10

struct Person:
    id: i32

impl Person:
    fn name(self: Person) -> i32:
        return self.id

fn main():
    p = Person{ id: 7 }
    print(p.greet())
"""
    r = run_src(tmp_path, src)
    assert r.stdout.split() == ["70"]


@needs_cc
def test_feature_keyword_execution(tmp_path):
    src = """
feature Describable:
    fn power(self: Self) -> i32
    fn bonus(self: Self) -> i32:
        return self.power() * 2

struct Weapon:
    base: i32

impl Weapon:
    fn power(self: Weapon) -> i32:
        return self.base

fn calc_bonus[T: Describable](x: T) -> i32:
    return x.bonus()

fn main():
    w = Weapon{ base: 50 }
    print(w.bonus())
    print(calc_bonus(w))
"""
    ok(tmp_path, src, ["100", "100"])


def test_default_method_when_owner_moves():
    """A field of type `string` makes `self` inferred `read`. That still implements `self: Self`."""
    src = """
feature Named:
    fn score(self: Self) -> i32
    fn rename(self: Self, next: string):
        self.title = next

struct Item:
    title: string
    n: i32

impl Item:
    fn score(self) -> i32:
        return self.n

fn main():
    it = Item{ title: string.from("gem"), n: 3 }
    it.rename(string.from("ore"))
    print(it.n)
"""
    assert messages(src) == []


def test_explicit_lend_is_still_required_when_owner_moves():
    src = """
feature Act:
    fn poke(self: lend Self)

struct Item:
    title: string

impl Item:
    fn poke(self):
        self.title = string.from("x")

fn go[T: Act](x: lend T):
    x.poke()

fn main():
    it = Item{ title: string.from("a") }
    go(it)
"""
    errs = messages(src)
    assert any("Act" in m and "poke" in m and "mode" in m for m in errs), errs


def test_default_method_across_modules(tmp_path):
    """Required methods live on the imported type; the default is still part of that type."""
    from greengold.cli import load_sources_and_ast
    from greengold.typecheck import check_program

    types = tmp_path / "types"
    types.mkdir()
    (types / "shapes.gg").write_text(
        "struct Rectangle:\n"
        "    name: string\n"
        "    width: f64\n"
        "    height: f64\n\n"
        "impl Rectangle:\n"
        "    fn new(width: f64, height: f64) -> Rectangle:\n"
        "        return Rectangle{ name: string.from(\"Rectangle\"), width: width, height: height }\n",
        encoding="utf-8",
    )
    traits = tmp_path / "traits"
    traits.mkdir()
    (traits / "shapes.gg").write_text(
        'import "../types/shapes.gg"\n\n'
        "feature AreaCalculatible:\n"
        "    fn get_area(self: Self) -> f64\n"
        "    fn set_name(self: Self, new_name: string):\n"
        "        self.name = new_name\n\n"
        "impl shapes.Rectangle:\n"
        "    fn get_area(self) -> f64:\n"
        "        return self.width * self.height\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "types/shapes.gg"\n'
        'import "traits/shapes.gg" as traitshape\n\n'
        "fn main():\n"
        "    rect = shapes.Rectangle.new(10.0, 30.0)\n"
        "    rect.set_name(string.from(\"box\"))\n"
        "    print(rect.get_area())\n",
        encoding="utf-8",
    )
    program, _, diags = load_sources_and_ast([str(main)])
    if not diags.has_errors():
        check_program(program, diags, str(main))
    errs = [d.message for d in diags.items if not d.hidden]
    assert errs == [], errs


@needs_cc
def test_default_method_mutates_moved_owner(tmp_path):
    src = """
feature Named:
    fn score(self: Self) -> i32
    fn rename(self: Self, next: string):
        self.title = next

struct Item:
    title: string
    n: i32

impl Item:
    fn score(self) -> i32:
        return self.n

fn main():
    it = Item{ title: string.from("gem"), n: 3 }
    it.rename(string.from("ore"))
    print(it.score())
    print(it.title)
"""
    ok(tmp_path, src, ["3", "ore"])




