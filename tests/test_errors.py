"""Error message tests: each is an invalid Greengold program and the expected message substring."""
import pytest

from .helpers import PREAMBLE, messages, with_main

# (id, source, expected substring)
CASES = [
    ("non-var-lend",
     with_main("fixed c = Counter{ value: 0 }\nbump(c)"),
     "declared `fixed`"),
    ("twice-lend",
     "struct P:\n    a: i32\n\nfn two(x: lend P, y: lend P):\n    x.a = 1\n\n"
     "fn main():\n    p = P{ a: 1 }\n    two(p, p)\n",
     "multiple times"),
    ("immutable-assign",
     with_main("fixed x = 5\nx = 6"),
     "Cannot assign"),
    ("immutable-field-assign",
     with_main("fixed c = Counter{ value: 0 }\nc.value = 3"),
     "Cannot assign to field"),
    ("assign-to-read-param",
     "struct P:\n    a: i32\n\nfn f(p: P):\n    p.a = 1\n\nfn main():\n    f(P{ a: 1 })\n",
     "value parameter"),
    ("use-after-consume",
     with_main("c = Counter{ value: 1 }\nfinish(c)\nshow(c)"),
     "`c` variable was moved (`consume`), can no longer be used."),
    ("consume-in-loop",
     with_main("c = Counter{ value: 1 }\ni = 0\nwhile i < 3:\n    finish(c)\n    i += 1"),
     "each iteration"),
    ("consume-in-for",
     with_main("c = Counter{ value: 1 }\nfor i in 0..3:\n    finish(c)"),
     "each iteration"),
    ("consume-primitive",
     "fn eat(n: consume i32):\n    print(n)\n\nfn main():\n    eat(1)\n",
     "i32 is copied, `consume` is not needed."),
    ("tab",
     "fn main():\n\tprint(1)\n",
     "Tab characters are not allowed"),
    ("double-slash-comment",
     "fn main():\n    print(1) // comment\n",
     "// is not a comment, use # for comments."),
    ("undefined-variable",
     "fn main():\n    print(y)\n",
     "`y` is not defined."),
    ("type-mismatch",
     "fn main():\n    x: i32 = 1.5\n",
     "Type mismatch: expected `i32`, found `f64`."),
    ("wrong-arg-count",
     "fn add(a: i32, b: i32) -> i32:\n    return a + b\n\nfn main():\n    print(add(1))\n",
     "`add` expects 2 argument(s), found 1."),
    ("unknown-field",
     with_main("c = Counter{ value: 1 }\nprint(c.valu)"),
     "Struct `Counter` has no field named `valu`."),
    ("unknown-method",
     with_main("c = Counter{ value: 1 }\nc.nothing()"),
     "Type `Counter` has no method named `nothing`."),
    ("missing-return",
     "fn f(a: i32) -> i32:\n    if a > 0:\n        return 1\n\nfn main():\n    print(f(1))\n",
     "not all paths have a `return`"),
    ("cannot-store-view-as-owned",
     with_main("v = List[List[i32]]()\ninner = List[i32]()\nv.push(inner)\nx: List[i32] = v.get(0)"),
     "view"),
    ("mutating-method-immutable",
     "struct P:\n    h: i32\n\nimpl P:\n    fn hit(self: lend P):\n        self.h -= 1\n\n"
     "fn main():\n    fixed p = P{ h: 3 }\n    p.hit()\n",
     "`hit` changes `p`"),
    ("consume-self-then-use",
     "struct P:\n    xs: List[i32]\n\nimpl P:\n    fn eat(self: consume P):\n        print(self.xs.len)\n\n"
     "fn main():\n    p = P{ xs: List[i32]() }\n    p.eat()\n    print(p.xs.len)\n",
     "was moved"),
    ("consume-in-if-branch",
     with_main("c = Counter{ value: 1 }\nflag = true\nif flag:\n    finish(c)\nshow(c)"),
     "was moved"),
    ("consume-via-lend-param",
     with_main("print(1)", preamble=PREAMBLE + "fn f(c: lend Counter):\n    finish(c)\n\n"),
     "you do not own it"),
]


@pytest.mark.parametrize("src,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_error_message(src, expected):
    msgs = messages(src)
    assert any(expected in m for m in msgs), msgs


def test_at_least_15_cases():
    assert len(CASES) >= 15


def test_multiple_errors_reported_together():
    src = "fn main():\n    fixed a = 1\n    a = 2\n    print(zzz)\n    b: i32 = 1.5\n"
    assert len(messages(src)) >= 3


def test_give_error_shows_move_line():
    from greengold.diagnostics import render_all
    from .helpers import front_end
    src = with_main("c = Counter{ value: 1 }\nfinish(c)\nshow(c)")
    _, diags = front_end(src)
    text = render_all(diags, src, "t.gg")
    assert "was moved" in text and "finish(c)" in text
