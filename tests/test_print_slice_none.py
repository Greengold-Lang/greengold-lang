"""`panic(f"...")`, printing structs / lists / enums, `str` slicing, and `x = None` type inference."""
import pytest

from .helpers import HAS_CC, messages, run_gg_source

needs_cc = pytest.mark.skipif(not HAS_CC, reason="gcc/clang not found")


# ---------------------------------------------------------------- panic with a computed message

@needs_cc
def test_panic_fstring_message(tmp_path):
    src = 'fn main():\n    x = 5\n    if x > 3:\n        panic(f"x too big: {x}")\n'
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 101
    assert "Runtime error: x too big: 5" in r.stderr
    assert "a.gg:4:9" in r.stderr


@needs_cc
def test_panic_string_variable(tmp_path):
    src = 'fn main():\n    s = string.from("broken")\n    panic(s)\n'
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 101
    assert "Runtime error: broken" in r.stderr


# ---------------------------------------------------------------- print / f-string of structured values

SHOW = """
struct Point:
    x: i64
    y: f64

struct Named:
    name: string
    tags: List[str]
    pos: Point

enum Shape:
    Circle(f64)
    Rect(i32, i32)
    Empty

struct Celsius:
    deg: i32

impl Celsius:
    fn to_string(self) -> string:
        return f"{self.deg}C"

fn make() -> List[i32]:
    xs = List[i32]()
    xs.push(7)
    return xs

fn main():
    p = Point{x: 1, y: 2.5}
    print(p)
    print([1, 2, 3], "after")
    l = List[string]()
    l.push(string.from("a"))
    l.push(string.from("b"))
    print(l)
    t = List[str]()
    t.push("x")
    n = Named{name: string.from("n"), tags: t, pos: p}
    print(n)
    print(Shape.Circle(1.5), Shape.Rect(2, 3), Shape.Empty)
    o: Optional[i32] = Valid(4)
    e: Result[i32, str] = Err("no")
    print(o, e)
    print(Celsius{deg: 21})
    print(make())
    print(f"p = {p}, l = {l}")
    print(List[i32]())
    print(p.x)
"""


@needs_cc
def test_print_structured_values(tmp_path):
    r = run_gg_source(tmp_path, SHOW)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "Point { x: 1, y: 2.5 }",
        "[1, 2, 3] after",
        '["a", "b"]',
        'Named { name: "n", tags: ["x"], pos: Point { x: 1, y: 2.5 } }',
        "Shape.Circle(1.5) Shape.Rect(2, 3) Shape.Empty",
        'Valid(4) Err("no")',
        "21C",
        "[7]",
        'p = Point { x: 1, y: 2.5 }, l = ["a", "b"]',
        "[]",
        "1",
    ]


def test_print_does_not_move_the_value():
    src = "fn main():\n    xs = List[i32]()\n    xs.push(1)\n    print(xs)\n    print(xs)\n    ys = xs\n"
    assert messages(src) == []


def test_print_rejects_pointer_inside_struct():
    src = "struct P:\n    p: *u8\n\nfn main():\n    x = P{p: null}\n    print(x)\n    s = f\"{x}\"\n"
    msgs = messages(src)
    assert "Type `P` cannot be printed: it contains `*u8`." in msgs
    assert "Type `P` cannot be formatted in a string literal: it contains `*u8`." in msgs


# ---------------------------------------------------------------- str slicing

@needs_cc
def test_str_slicing(tmp_path):
    src = """fn first(s: str) -> str:
    return s[0..1]

fn main():
    s = "hello"
    print(s[1..3])
    t = s[2..]
    print(t, s[..2], s[1..=3], first(s))
    o = string.from("world")
    print(o[1..4])
    print("çay"[0..2])
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["el", "llo he ell h", "orl", "ç"]


@needs_cc
def test_str_slice_out_of_range_and_mid_character(tmp_path):
    r = run_gg_source(tmp_path, 'fn main():\n    s = "abc"\n    n = 5\n    print(s[1..n])\n')
    assert r.returncode == 101
    assert "slice range out of bounds" in r.stderr
    r = run_gg_source(tmp_path, 'fn main():\n    s = "çay"\n    print(s[0..1])\n')
    assert r.returncode == 101
    assert "inside a UTF-8 character" in r.stderr


# ---------------------------------------------------------------- `x = None` without a type

@needs_cc
def test_none_type_comes_from_later_use(tmp_path):
    src = """fn take(o: Optional[str]) -> str:
    return o.value_or("none")

fn main():
    x = None
    print(x)
    x = Valid(3)
    print(x, x.value_or(0))
    y = None
    print(take(y))
    z = None
    if true:
        z = Valid(string.from("hi"))
    print(z)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["None", "Valid(3) 3", "none", 'Valid("hi")']


def test_none_with_no_use_reports_once():
    msgs = messages("fn main():\n    x = None\n    print(x)\n")
    assert msgs == ["The type of `x` could not be inferred: `None` alone does not name it."]


def test_none_then_wrong_type_is_a_mismatch():
    msgs = messages("fn main():\n    x = None\n    x = Valid(3)\n    x = Valid(\"s\")\n")
    assert any("mismatch" in m.lower() for m in msgs), msgs
