"""self-hosting step 2 - the Greengold parser (selfhost/parser.gg) must agree with greengold/parser.py."""
import subprocess
import sys
from pathlib import Path

import pytest

from greengold.ast_nodes import dump_ast
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse
from tests.helpers import ROOT

PARSER_SRC = ROOT / "selfhost" / "parser.gg"

SNIPPETS = [
    "fn main():\n    x = 1 + 2\n",
    "fn main():\n    x: read = y\n",
    "struct P:\n    a: lend Q\n",
    "fn main():\n    x = consume 5\n",
    "fn main():\n    x = \n",
    "fn main():\n    if a:\n        return\n    else if b:\n        return\n",
    "x = 5\n",
    "fn main():\n    x = \n    y = 5\n    z = (\n    w = 1 2\n",
    "fn P.hit(self: lend P, n: i32):\n    self.h -= n\n",
    'fn main():\n    s = f"hi {1 + 2}"\n',
    'fn main():\n    s = f"a{{b}}c"\n',
    "fn main():\n    if a then 1 else 2\n",
    "fn main():\n    x = match n:\n        1 => 10\n        2..=4 => 20\n        _ => 0\n",
    "enum Color:\n    Red\n    Green(i32)\n",
    "fn main():\n    unsafe:\n        x = 1\n",
    "fn main():\n    wrapping:\n        x = a + b\n",
    "fn f() overflow: wrap:\n    return\n",
    "test:\n    x = 1\n",
    "test smoke:\n    x = 1\n",
    "type Meters = i32\nfn main():\n    x = Meters(1)\n",
    "fn main():\n    xs[i] = 1\n",
    "fn main():\n    a, b = pair\n",
    "fn main():\n    if let Valid(n) = opt:\n        return n\n",
    "fn main():\n    while let Valid(n) = next():\n        use(n)\n",
    "fn main():\n    for i, x in xs:\n        use(x)\n",
    "fn main():\n    for x in xs:\n        x = 1\n",
    "fn main():\n    defer close(f)\n",
    "fn main():\n    require n > 0\n",
    "public\nfn f():\n    return\nprivate\nfn g():\n    return\n",
    'import std.math\nimport "file.gg" as io\n',
    "extern fn sqrt(x: f64) -> f64\n",
    "fn main():\n    x = math.max[i32](1, 2)\n",
    "fn id[T](x: T) -> T:\n    return x\n",
    "struct Pair[T, U]:\n    a: T\n    b: U\n",
    "fn main():\n    x = a and b or not c\n",
    "fn main():\n    x = a < b < c\n",
    "fn main():\n  x = 1\n",
    "fn main():\n    if x:\n        return\n  y = 1\n",
    "fn main():\n    x = [1, 2,]\n",
    "fn main():\n    p = P{ x: 1 y: 2 }\n",
    "fn main():\n    c = '\\n'\n",
    "fn main():\n    x = -1\n",
    "fn main():\n    x = ~a\n",
    "fn main():\n    x = a ?\n",
    "fn main():\n    x = xs[1..]\n",
    "fn main():\n    x = xs[..3]\n",
    "fn main():\n    x = xs[1..=3]\n",
    "fn main():\n    x = copy a\n",
    "fn main():\n    x = trust xs[i]\n",
    "feature Show:\n    fn show(self: read Show) -> string\n",
    "const N: i32 = 4\n",
    "fn main():\n    x: *mut i32 = p\n",
    "fn f[T: Ord](x: T):\n    return\n",
    "impl combat.Hero:\n    fn hit(self: lend Hero):\n        return\n",
    "fn main():\n    match m consume:\n        Valid(n):\n            use(n)\n        None:\n            pass\n",
    "enum E:\n    A = 1\n",
    'fn main():\n    x = f"{ }\n',
    "fn main():\n    pass\n",
    "fn main():\n    yield 1\n",
    "fn main():\n    for i in range 10:\n        pass\n",
    "fn main():\n    for i in range 0..n step 2:\n        pass\n",
    "type Box[T] = List[T]\n",
    "fn main():\n    x = (1, 2, 3)\n",
    "fn main():\n    f = |a: i32| a + 1\n",
    "fn main():\n    x = soa Vec3()\n",
    "struct S:\n    hot x: i32\n",
    "fn main():\n    x = a wrapping_add b\n",
    "extern fn puts(s: *u8, ...) -> i32\n",
    "fn main():\n    x: i32 in 0..10 = 3\n",
    "fn main():\n    x = [i32; 4]\n",
    "fn main():\n    x = Array[i32, 4]\n",
    "type A = B\ntype B = i32\nfn main():\n    x: A = 1\n",
    "type Id = Pair\nfn main():\n    x = Id{ a: 1 }\n",
    "type Box[T] = List[T]\nfn main():\n    x = Box(1)\n",
    "type A = A\nfn main():\n    x: A = 1\n",
]


def py_dump(text: str) -> list[str]:
    diags = DiagnosticBag()
    prog = parse(tokenize(text, diags), diags)
    lines = dump_ast(prog).splitlines()
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


def corpus() -> list[Path]:
    files = sorted((ROOT / "examples").glob("*.gg"))
    files += sorted((ROOT / "greengold" / "std").glob("*.gg"))
    files += [ROOT / "greengold" / "core" / "core.gg"]
    files += sorted((ROOT / "selfhost").glob("*.gg"))
    good = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if text.isascii() and "\t" not in text:
            good.append(f)
    return good


def first_diff(expect: list[str], got: list[str]) -> str:
    n = max(len(expect), len(got))
    for i in range(n):
        a = expect[i] if i < len(expect) else "<missing>"
        b = got[i] if i < len(got) else "<missing>"
        if a != b:
            return f"line {i + 1}: {a!r} != {b!r}"
    return "exit code"


@pytest.fixture(scope="module")
def parser_exe(tmp_path_factory):
    exe = tmp_path_factory.mktemp("selfhost") / ("parser" + (".exe" if sys.platform == "win32" else ""))
    r = subprocess.run(
        [sys.executable, "-m", "greengold", "build", str(PARSER_SRC), "-o", str(exe)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300,
    )
    assert r.returncode == 0, r.stderr
    return exe


def run_selfhost(exe: Path, text: str, tmp: Path) -> subprocess.CompletedProcess:
    (tmp / "gg_selfhost_in.txt").write_bytes(text.encode("utf-8"))
    return subprocess.run([str(exe)], capture_output=True, cwd=tmp, timeout=120)


def test_corpus_is_not_trivial():
    assert len(corpus()) >= 20


def test_parser_matches_python_on_corpus(parser_exe, tmp_path):
    mismatches = []
    for f in corpus():
        text = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        expect = py_dump(text)
        r = run_selfhost(parser_exe, text, tmp_path)
        got = r.stdout.decode("utf-8").splitlines()
        want_fail = any(line.startswith("DIAG ") for line in expect)
        code_bad = (r.returncode != 0) if not want_fail else (r.returncode == 0)
        if got != expect or code_bad:
            mismatches.append(f"{f.name}: {first_diff(expect, got)}")
    assert not mismatches, mismatches[0]


def test_parser_matches_python_on_snippets(parser_exe, tmp_path):
    mismatches = []
    for src in SNIPPETS:
        expect = py_dump(src)
        r = run_selfhost(parser_exe, src, tmp_path)
        got = r.stdout.decode("utf-8").splitlines()
        want_fail = any(line.startswith("DIAG ") for line in expect)
        code_bad = (r.returncode != 0) if not want_fail else (r.returncode == 0)
        if got != expect or code_bad:
            mismatches.append(f"{src.splitlines()[0]}: {first_diff(expect, got)}")
    assert not mismatches, mismatches[0]
