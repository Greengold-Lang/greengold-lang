"""`dyn Feature`: owned values of different types behind one feature, called through a method table."""
import pytest

from .helpers import messages, run_built

FEATURE = """feature Shape:
    fn area(self: Self) -> f64
    fn name(self: Self) -> string
    fn grow(self: lend Self, by: f64)
    fn same(self: Self, other: Self) -> bool
    fn describe(self: Self) -> string:
        return f"{self.name()} {self.area()}"

struct Sq:
    s: f64

impl Sq:
    fn area(self) -> f64:
        return self.s * self.s

    fn name(self) -> string:
        return "sq"

    fn grow(self: lend Self, by: f64):
        self.s += by

    fn same(self, other: Sq) -> bool:
        return self.s == other.s

struct Bag:
    label: string
    xs: List[f64]

impl Bag:
    fn area(self) -> f64:
        t = 0.0
        for x in self.xs:
            t += x
        return t

    fn name(self) -> string:
        return self.label.clone()

    fn grow(self: lend Self, by: f64):
        self.xs.push(by)

    fn same(self, other: Bag) -> bool:
        return false

    fn drop(self: lend Self):
        print(f"drop {self.label}")

"""


def run(body):
    res = run_built(FEATURE + "fn main():\n" + "".join("    " + l + "\n" for l in body.splitlines()))
    assert res.returncode == 0, res.stderr
    return res.stdout.splitlines()


def test_list_of_dyn_calls_each_type():
    out = run("shapes = List[dyn Shape]()\nshapes.push(Sq{ s: 2.0 })\nshapes.push(Bag{ label: \"b\", xs: List[f64]() })\n"
              "for s in shapes:\n    s.grow(1.0)\nfor s in shapes:\n    print(s.describe())")
    assert out == ["sq 9", "b 1", "drop b"]


def test_dyn_parameter_and_drop_once():
    src = FEATURE + ("fn show(s: read dyn Shape):\n    print(s.area())\n\n"
                     "fn take(s: consume dyn Shape):\n    print(s.name())\n\n"
                     "fn main():\n    a: dyn Shape = Bag{ label: \"a\", xs: List[f64]() }\n    show(a)\n    take(a)\n"
                     "    print(\"end\")\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["0", "a", "drop a", "end"]


@pytest.mark.parametrize("body, text", [
    ("x: dyn Shape = Sq{ s: 1.0 }\ny: dyn Shape = Sq{ s: 1.0 }\nprint(x.same(y))", "mentions `Self`"),
    ("x: dyn Shape = 5", "cannot be a `dyn Shape`"),
    ("x: dyn Shape = Sq{ s: 1.0 }\ny = x\nprint(x.area())", "was moved"),
    ("x: dyn Shape = Sq{ s: 1.0 }\nprint(x.perimeter())", "has no method named `perimeter`"),
    ("x: dyn Nope = Sq{ s: 1.0 }", "`dyn` needs a feature"),
    ("fixed x: dyn Shape = Sq{ s: 1.0 }\nx.grow(1.0)", "fixed"),
])
def test_dyn_errors(body, text):
    msgs = messages(FEATURE + "fn main():\n" + "".join("    " + l + "\n" for l in body.splitlines()))
    assert any(text in m for m in msgs), msgs


def test_type_holding_a_view_cannot_be_dyn():
    src = FEATURE.replace("    label: string", "    label: str").replace("self.label.clone()", "self.label.to_string()")
    msgs = messages(src + "fn main():\n    x: dyn Shape = Bag{ label: \"a\", xs: List[f64]() }\n")
    assert any("holds a `str` view" in m for m in msgs), msgs
