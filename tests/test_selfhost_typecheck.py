"""the Greengold type checker core must agree with greengold/typecheck.py.

This slice covers literals, names, arithmetic, calls, functions, main, assignment,
struct fields, struct literals, methods, range / integer loops, enums, match,
arrays, indexing, slices, constants, if/match expressions, move analysis,
borrow checking, generic type applications (prelude Optional/Result/List/Box/string
and user generic structs), and generic function and method instantiation.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse
from greengold.typecheck import check_program
from tests.helpers import ROOT

TC_SRC = ROOT / "selfhost" / "tc.gg"
CORE_SRC = ROOT / "greengold" / "core" / "core.gg"

SNIPPETS = [
    "fn main():\n    x = 1 + 2 * 3\n",
    "fn main():\n    x: i32 = true\n",
    "fn main():\n    y = missing\n",
    "fn add(a: i32, b: i32) -> i32:\n    return a + b\n",
    "fn main():\n    return 1\n",
    "fn f() -> i32:\n    x = 1\n",
    "fn main():\n    if 1:\n        return\n",
    "fn main():\n    x = 1 + true\n",
    "struct P:\n    x: i32\nfn main():\n    return\n",
    "fn main(n: i32):\n    return\n",
    "struct P:\n    x: i32\n",
    "fn main():\n    x = 1\n    x = 2\n",
    "fn main():\n    x = 1\n    x = 2\n",
    "fn main():\n    x: Unknown = 1\n",
    "fn main():\n    x = 1\n    y = x\n",
    "fn main():\n    x = 1 < 2\n",
    "fn main():\n    while true:\n        break\n",
    "fn main():\n    break\n",
    "fn add(a: i32, b: i32) -> i32:\n    return a + b\nfn main():\n    x = add(1, 2)\n",
    "fn add(a: i32, b: i32) -> i32:\n    return a + b\nfn main():\n    x = add(1)\n",
    "fn main():\n    x = no_such(1)\n",
    "fn main():\n    print(1)\n",
    "fn main():\n    x = not true\n",
    "fn main():\n    x = -1\n",
    "fn f(n: consume i32):\n    return\nfn main():\n    return\n",
    "fn main():\n    x: i64 = 1\n",
    "fn main():\n    if true:\n        return\n    else:\n        return\n",
    "struct P:\n    x: i32\n    y: i32\nfn main():\n    p = P{ x: 1, y: 2 }\n    n = p.x\n",
    "struct P:\n    x: i32\nfn main():\n    p = P{ x: 1 }\n",
    "struct P:\n    x: i32\nfn main():\n    p = P{ z: 1 }\n",
    "struct P:\n    x: i32\nfn main():\n    n = 1\n    a = n.x\n",
    "struct P:\n    x: i32\nfn main():\n    p = P{ x: 1 }\n    a = p.z\n",
    "struct P:\n    x: i32\nimpl P:\n    fn hit(self: lend P, n: i32):\n        self.x = n\nfn main():\n    p = P{ x: 1 }\n    p.hit(2)\n",
    "struct P:\n    x: i32\nimpl P:\n    fn hit(self: lend P, n: i32):\n        self.x = n\nfn main():\n    p = P{ x: 1 }\n    p.hit(2)\n",
    "struct P:\n    x: i32\nfn main():\n    p = P{ x: 1 }\n    p.x = 3\n",
    "struct P:\n    x: i32\nfn main():\n    p = P{ x: 1 }\n    p.x = 3\n",
    "struct P:\n    x: i32\nimpl P:\n    fn get(self: read P) -> i32:\n        return self.x\nfn main():\n    p = P{ x: 4 }\n    n = p.get()\n",
    "struct P:\n    x: i32\nimpl P:\n    fn hit(self: lend P):\n        return\nfn main():\n    p = P{ x: 1 }\n    p.nope()\n",
    "struct P:\n    x: i32\nfn main():\n    p = P{ x: true }\n",
    "struct P:\n    x: i32\nimpl P:\n    fn make(n: i32) -> P:\n        return P{ x: n }\nfn main():\n    p = P.make(3)\n",
    "fn main():\n    for i in 0..3:\n        return\n",
    "fn main():\n    for i in 0..=3:\n        x = i\n",
    "fn main():\n    n = 4\n    for i in n:\n        x = i\n",
    "fn main():\n    for i in 0..10 step 2:\n        return\n",
    "fn main():\n    for i in 10..0 step -1:\n        return\n",
    "fn main():\n    for i in true..1:\n        return\n",
    "fn main():\n    for i in 0..true:\n        return\n",
    "fn main():\n    for i in 0..10 step 0:\n        return\n",
    "fn main():\n    n = 2\n    for i in 0..10 step n:\n        return\n",
    "fn main():\n    for i in 3:\n        return\n",
    "fn main():\n    for i in true:\n        return\n",
    "fn main():\n    for i in 0..2:\n        break\n",
    "fn main():\n    a: i8 = 0\n    b: i8 = 10\n    for i in a..b step 300:\n        return\n",
    "fn main():\n    a: u32 = 0\n    b: u32 = 4\n    for i in a..b step -1:\n        return\n",
    "fn main():\n    n: i64 = 8\n    for i in 0..n:\n        x = i + 1\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Empty\n    match s:\n        Empty:\n            return\n        Circle(r):\n            n = r\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Circle(3)\n    match s:\n        Empty:\n            return\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Nope\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Circle()\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Empty()\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Circle(true)\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Circle(1, 2)\n",
    "fn main():\n    n = 1\n    match n:\n        1:\n            return\n        _:\n            return\n",
    "fn main():\n    match true:\n        true:\n            return\n",
    "fn main():\n    match 1:\n        1:\n            return\n        1:\n            return\n        _:\n            return\n",
    "fn f() -> i32:\n    match true:\n        true:\n            return 1\n        false:\n            return 2\nfn main():\n    return\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Empty\n    match s:\n        Empty:\n            return\n        Empty:\n            return\n        Circle(r):\n            return\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Empty\n    match s:\n        Circle(r, z):\n            return\n        _:\n            return\n",
    "enum Color:\n    Red\n    Blue\nfn main():\n    c = Color.Red\n    match c:\n        Color.Red:\n            return\n        Blue:\n            return\n",
    "fn main():\n    s = 1.5\n    match s:\n        _:\n            return\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Empty\n    match lend s:\n        Empty:\n            return\n        Circle(r):\n            return\n",
    "fn main():\n    match 1:\n        0..=2:\n            return\n        _:\n            return\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nenum Shape:\n    Other\nfn main():\n    return\n",
    "enum Shape:\n    Empty\n    Empty\nfn main():\n    return\n",
    "fn main():\n    x = \"a\"\n    match x:\n        \"a\":\n            return\n        \"a\":\n            return\n        _:\n            return\n",
    "fn main():\n    a = [1, 2, 3]\n    n = a[0]\n    k = a.len\n",
    "fn main():\n    a: [3]i32 = [1, 2, 3]\n    n = a[1] + 1\n",
    "fn main():\n    a: [2]i32 = [1, 2, 3]\n",
    "fn main():\n    a = []\n",
    "fn main():\n    a: [3]i32 = []\n",
    "fn main():\n    a = [0; 4]\n    n = a[3]\n",
    "fn main():\n    a = [1, 2, 3]\n    n = a[5]\n",
    "fn main():\n    a = [1, 2, 3]\n    n = a[true]\n",
    "fn main():\n    n = 1\n    k = n[0]\n",
    "fn main():\n    s = \"hi\"\n    n = s[0]\n",
    "fn main():\n    n = \"hi\"[5]\n",
    "fn main():\n    n = \"hi\"[-1]\n",
    "fn main():\n    a = [1, 2, 3, 4]\n    s = a[1..3]\n",
    "fn f(xs: []i32):\n    return\nfn main():\n    a = [1, 2, 3, 4]\n    f(a[1..3])\n",
    "fn main():\n    a = [1, 2, 3]\n    for x in a:\n        n = x\n",
    "fn main():\n    for x in \"ab\":\n        n = x\n",
    "fn main():\n    a: [2]i32 = [1; 2]\n",
    "fn main():\n    a = [1, true]\n",
    "fn main():\n    s = \"hi\"[1..2]\n",
    "fn main():\n    a: [2 * 2]i32 = [1, 2, 3, 4]\n",
    "fn main():\n    for x in [10, 20]:\n        n = x + 1\n",
    "const N = 3\nfn main():\n    x = N + 1\n",
    "const N: i64 = 4\nfn main():\n    x: i64 = N\n",
    "const A = 1\nconst B = A + 2\nfn main():\n    x = B\n",
    "const B = A\nconst A = 1\nfn main():\n    return\n",
    "const N = missing\nfn main():\n    return\n",
    "const N = 1\nconst N = 2\nfn main():\n    return\n",
    "struct P:\n    x: i32\nconst P = 1\nfn main():\n    return\n",
    "const i32 = 1\nfn main():\n    return\n",
    "const N = 1\nfn main():\n    N = 2\n",
    "fn main():\n    x = if true then 1 else 2\n",
    "fn main():\n    x = if true then 1 else true\n",
    "fn main():\n    x: i64 = if true then 1 else 2\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Circle(4)\n    n = match s:\n        Empty => 0\n        Circle(r) => r\n",
    "const N = 1 + 2 * 3\nfn main():\n    x = N\n",
    "fn f(a: [N]i32):\n    return\nconst N = 3\nfn main():\n    return\n",
    "const N = print(1)\nfn main():\n    return\n",
    "enum Shape:\n    Empty\n    Circle(i32)\nfn main():\n    s = Shape.Empty\n    n = match s:\n        Empty => 1\n        Circle(r) => true\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn main():\n    c = Counter{ value: 1 }\n    finish(c)\n    print(c.value)\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn main():\n    c = Counter{ value: 1 }\n    finish(c)\n    c = Counter{ value: 2 }\n    print(c.value)\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn f(flag: bool):\n    c = Counter{ value: 1 }\n    if flag:\n        finish(c)\n        return\n    print(c.value)\nfn main():\n    f(true)\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn main():\n    c = Counter{ value: 1 }\n    if true:\n        print(1)\n    else:\n        finish(c)\n    print(c.value)\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn main():\n    for i in 0..3:\n        c = Counter{ value: i }\n        finish(c)\n",
    "struct Counter:\n    value: i32\nfn two(a: consume Counter, b: consume Counter):\n    print(1)\nfn main():\n    c = Counter{ value: 1 }\n    two(c, c)\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn f(c: Counter):\n    finish(c)\nfn main():\n    print(1)\n",
    "struct Counter:\n    value: i32\nfn finish(c: consume Counter):\n    print(c.value)\nfn main():\n    c = Counter{ value: 1 }\n    for i in 0..2:\n        finish(c)\n",
    "enum Shape:\n    Empty\n    Circle(f64)\nfn main():\n    s = Shape.Empty\n    match consume s:\n        _:\n            pass\n    match s:\n        _:\n            pass\n",
    "enum Shape:\n    Empty\n    Circle(f64)\nfn f(s: Shape):\n    match consume s:\n        _:\n            pass\nfn main():\n    pass\n",
    "struct In:\n    v: i32\nstruct Out:\n    a: In\n    b: In\nfn eat(x: consume In):\n    print(x.v)\nfn main():\n    o = Out{ a: In{ v: 1 }, b: In{ v: 2 } }\n    eat(o.a)\n    print(o.b.v)\n",
    "struct P:\n    a: i32\nfn two(x: lend P, y: lend P):\n    x.a = 1\nfn main():\n    p = P{ a: 1 }\n    two(p, p)\n",
    "struct P:\n    a: i32\nfn both(x: lend P, y: read P):\n    x.a = 1\nfn main():\n    p = P{ a: 1 }\n    both(p, p)\n",
    "struct P:\n    a: i32\nfn both(x: lend P, y: consume P):\n    x.a = 1\nfn main():\n    p = P{ a: 1 }\n    both(p, p)\n",
    "fn main():\n    x = 1\n    w: lend i32 = x\n    print(x)\n    print(w)\n",
    "fn main():\n    x = 1\n    r: read i32 = x\n    print(x)\n    print(r)\n",
    "fn main():\n    hero = 1\n    slot: read i32 = hero\n    if true:\n        inner = 2\n        slot = inner\n    print(slot)\n",
    "struct P:\n    a: i32\nstruct Q:\n    r: lend P tied to other\nfn main():\n    print(1)\n",
    "fn f(a: read i32 tied to a):\n    print(a)\nfn main():\n    print(1)\n",
    "fn f(a: i32, b: read i32 tied to a):\n    print(b)\nfn main():\n    print(1)\n",
    "fn main():\n    x = 1\n    w: lend i32 = x\n    print(w)\n",
    "fn main():\n    x = Optional[i32].Valid(5)\n",
    "fn main():\n    x = Optional[i32].None\n",
    "fn main():\n    x = Result[i32, str].Ok(1)\n",
    "fn f(xs: List[i32]):\n    pass\nfn main():\n    pass\n",
    "fn main():\n    s = string.from(\"hi\")\n",
    "struct Pair[T]:\n    v: T\nfn main():\n    x = Pair[i32]{ v: 1 }\n",
    "fn f(x: Optional[i32, bool]):\n    pass\nfn main():\n    pass\n",
    "fn f(x: i32[bool]):\n    pass\nfn main():\n    pass\n",
    "fn f(x: List[[]i32]):\n    pass\nfn main():\n    pass\n",
    "fn f(x: Optional):\n    pass\nfn main():\n    pass\n",
    "fn f(x: Nope[i32]):\n    pass\nfn main():\n    pass\n",
    "fn main():\n    x = Optional[i32].Valid(true)\n",
    "fn main():\n    x = Optional[i32].Valid(5)\n    y = Optional[i32].None\n    print(x.has_value())\n    print(y.is_none())\n",
    "fn id[T](x: T) -> T:\n    return x\nfn main():\n    n = id(1)\n",
    "fn id[T](x: T) -> T:\n    return x\nfn main():\n    n = id[i64](1)\n",
    "struct Pair[T]:\n    v: T\nimpl Pair[T]:\n    fn get(self: read Pair[T]) -> T:\n        return self.v\nfn main():\n    p = Pair[i32]{ v: 1 }\n    n = p.get()\n",
    "fn main():\n    x = Optional[string].Valid(string.from(\"hi\"))\n    y = x.value_or(string.from(\"no\"))\n",
    "fn pick[T](a: T, b: T) -> T:\n    return a\nfn main():\n    n = pick(1, true)\n",
    "fn pick[T](a: T, b: T) -> T:\n    return a\nfn main():\n    n = pick(1, 2.0)\n",
    "fn pick[T](a: T, b: T) -> T:\n    return a\nfn main():\n    x = true\n    y = 1\n    n = pick(x, y)\n",
    "fn id[T](x: T) -> T:\n    return x\nfn main():\n    n = id()\n",
    "fn id[T](x: T) -> T:\n    return x\nfn main():\n    n = id[i32, bool](1)\n",
    "fn add(a: i32, b: i32) -> i32:\n    return a + b\nfn main():\n    n = add[i32](1, 2)\n",
    "fn id[T](x: i32) -> T:\n    return x\nfn main():\n    n = id(1)\n",
    "struct Pair[T]:\n    v: T\nimpl Pair[T]:\n    fn get(self: read Pair[T]) -> T:\n        return self.v\nfn main():\n    p = Pair[string]{ v: string.from(\"hi\") }\n    n = p.get()\n",
    "fn id[T](x: T) -> T:\n    y = x\n    return y\nfn main():\n    s = id(string.from(\"hi\"))\n",
    "fn main():\n    x = Optional[i32].Valid(1)\n    x.nope()\n",
]


def py_diags(text: str) -> list[str]:
    diags = DiagnosticBag()
    prog = parse(tokenize(text, diags), diags)
    if not diags.has_errors():
        check_program(prog, diags, "<source>")
    lines = []
    for e in diags.items:
        lines.extend(f"DIAG {e.code} {e.line} {e.col} {e.length} {e.message}".splitlines())
        if e.hint:
            lines.extend(f"HINT {e.hint}".splitlines())
        for fix in e.fixes:
            for ed in fix.edits:
                lines.extend(
                    f"FIX {fix.applicability}|{fix.description}|{ed.start_line}:{ed.start_col}:{ed.end_line}:{ed.end_col}|{ed.replacement}".splitlines()
                )
    return lines


def first_diff(expect: list[str], got: list[str]) -> str:
    n = max(len(expect), len(got))
    for i in range(n):
        a = expect[i] if i < len(expect) else "<missing>"
        b = got[i] if i < len(got) else "<missing>"
        if a != b:
            return f"line {i + 1}: {a!r} != {b!r}"
    return "exit code"


@pytest.fixture(scope="module")
def checker_exe(tmp_path_factory):
    exe = tmp_path_factory.mktemp("selfhost") / ("tc" + (".exe" if sys.platform == "win32" else ""))
    r = subprocess.run(
        [sys.executable, "-m", "greengold", "build", str(TC_SRC), "-o", str(exe)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300,
    )
    assert r.returncode == 0, r.stderr
    return exe


def run_selfhost(exe: Path, text: str, tmp: Path) -> subprocess.CompletedProcess:
    (tmp / "gg_selfhost_in.txt").write_bytes(text.encode("utf-8"))
    (tmp / "gg_prelude.gg").write_bytes(CORE_SRC.read_bytes())
    return subprocess.run([str(exe)], capture_output=True, cwd=tmp, timeout=120)


def test_typecheck_core_matches_python(checker_exe, tmp_path):
    mismatches = []
    for src in SNIPPETS:
        expect = py_diags(src)
        r = run_selfhost(checker_exe, src, tmp_path)
        got = r.stdout.decode("utf-8").splitlines()
        want_fail = any(line.startswith("DIAG ") for line in expect)
        code_bad = (r.returncode != 0) if not want_fail else (r.returncode == 0)
        if got != expect or code_bad:
            mismatches.append(f"{src.splitlines()[0]}: {first_diff(expect, got)}")
    assert not mismatches, mismatches[0]
