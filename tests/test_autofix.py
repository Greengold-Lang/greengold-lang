"""Friendly front end: habits from other languages, `gg fix`, recovery after a syntax error, suggestions,
and the conversions that cannot lose information."""
import pytest

from greengold.cli import analyze, fix_source
from greengold.diagnostics import prepare

from .helpers import HAS_CC, messages, run_gg_source


def _fixed(tmp_path, src: str, likely: bool = False) -> tuple[str, list]:
    f = tmp_path / "a.gg"
    f.write_text(src, encoding="utf-8")
    new, applied, remaining = fix_source(src, str(f), likely)
    return new, [d for d in remaining if d.severity == "error"]


def _visible(tmp_path, src: str):
    f = tmp_path / "a.gg"
    f.write_text(src, encoding="utf-8")
    _prog, _sources, diags, _checker = analyze([str(f)])
    return prepare(diags.items)


@pytest.mark.parametrize("src, expected", [
    ("fn main():\n    x = 1\n    if x == 1 && x < 2 || !false:\n        print(x)\n",
     "fn main():\n    x = 1\n    if x == 1 and x < 2 or not false:\n        print(x)\n"),
    ("fn main():\n    x = 1\n    x++\n    print(x);\n", "fn main():\n    x = 1\n    x += 1\n    print(x)\n"),
    ("fn main():\n    a = 1; b = 2\n    print(a, b)\n", "fn main():\n    a = 1\n    b = 2\n    print(a, b)\n"),
    ("fn main():\n    let x = 5\n    print(x)\n", "fn main():\n    x = 5\n    print(x)\n"),
    ("def main():\n    print(1) // one\n", "fn main():\n    print(1) # one\n"),
    ("fn main()\n    print(1)\n", "fn main():\n    print(1)\n"),
    ("const N = 3\n\nfn main():\n    print(N)\n", "const N = 3\n\nfn main():\n    print(N)\n"),
    ("fn main():\n    print(Some(3).value_or(0))\n", "fn main():\n    print(Valid(3).value_or(0))\n"),
    ("fn main():\n    xs = List[i32]()\n    xs.append(1)\n    print(xs.len)\n",
     "fn main():\n    xs = List[i32]()\n    xs.push(1)\n    print(xs.len)\n"),
    ("fn main():\n    print(sqrt(4.0))\n", "import std.math\nfn main():\n    print(math.sqrt(4.0))\n"),
    ("fn main():\n    x = 5\n    print(x)\n", "fn main():\n    x = 5\n    print(x)\n"),
    ("fn main():\n    xs = List[i32]()\n    print(len(xs))\n", "fn main():\n    xs = List[i32]()\n    print(xs.len)\n"),
])
def test_safe_fixes_repair_the_file(tmp_path, src, expected):
    new, errors = _fixed(tmp_path, src)
    assert new == expected
    assert errors == []


def test_method_written_outside_impl_moves_into_impl(tmp_path):
    src = ("struct P:\n    x: i32\n\nfn P.get(self) -> i32:\n    return self.x\n\n"
           "fn main():\n    print(P{ x: 2 }.get())\n")
    new, errors = _fixed(tmp_path, src)
    assert "impl P:\n    fn get(self) -> i32:\n        return self.x\n" in new
    assert errors == []


def test_likely_fixes_need_the_flag(tmp_path):
    src = "fn main():\n    count = 1\n    print(cuont)\n"
    new, errors = _fixed(tmp_path, src)
    assert new == src and errors
    new, errors = _fixed(tmp_path, src, likely=True)
    assert "print(count)" in new and errors == []


def test_missing_match_arms_are_added(tmp_path):
    src = "enum E:\n    A\n    B\n\nfn main():\n    match E.A:\n        A:\n            print(1)\n"
    new, errors = _fixed(tmp_path, src, likely=True)
    assert "        B:\n            pass\n" in new and errors == []


def test_ambiguous_indent_takes_the_only_level_that_compiles(tmp_path):
    src = "fn main():\n    print(1)\n  print(2)\n"
    new, errors = _fixed(tmp_path, src)
    assert new == "fn main():\n    print(1)\n    print(2)\n" and errors == []


def test_syntax_error_does_not_hide_type_errors(tmp_path):
    shown = _visible(tmp_path, "fn main():\n    print(y)\n    retrun 1\n    print(z)\n")
    names = sorted(d.message for d in shown)
    assert any("`y` is not defined" in m for m in names)
    assert any("`z` is not defined" in m for m in names)
    assert any("does not perform any action" in m for m in names)


def test_names_from_a_skipped_line_are_cascades(tmp_path):
    shown = _visible(tmp_path, "fn main():\n    x = (1 +\n    print(x)\n")
    assert not any("`x` is not defined" in d.message for d in shown)


def test_every_foreign_operator_on_a_line_is_reported():
    msgs = messages("fn main():\n    if true && false || !true:\n        pass\n")
    assert sum("is not Greengold syntax" in m for m in msgs) == 3


def test_lossless_conversions_type_check():
    src = ("struct R:\n    id: i64\n    name: string\n\n"
           "fn wide(x: i64) -> i64:\n    return x\n\n"
           "fn main():\n    a: i32 = 3\n    b: i64 = 4\n    f: f64 = a\n"
           "    r = R{ id: a, name: \"n\" }\n    total: usize = 0\n"
           "    for i in 0..3:\n        total += i\n"
           "    print(a + b, wide(a), f, r.id, r.name, total, a < b)\n")
    assert messages(src) == []


@pytest.mark.parametrize("body", ["n: i32 = 1\n    m: usize = n", "big: i64 = 5\n    g: f64 = big",
                                  "big: i64 = 5\n    k: i32 = big"])
def test_lossy_conversions_still_need_a_cast(body):
    msgs = messages(f"fn main():\n    {body}\n")
    assert any("Type mismatch" in m for m in msgs)


def test_lend_argument_does_not_convert():
    msgs = messages("fn bump(x: lend i64):\n    x += 1\n\nfn main():\n    n: i32 = 1\n    bump(n)\n")
    assert any("Type mismatch" in m for m in msgs)


def test_len_spellings_and_string_literal_conversion():
    src = ("fn greet(n: string):\n    print(n)\n\n"
           "fn main():\n    xs = List[i32]()\n    s = string.from(\"ab\")\n    t: string = \"x\"\n"
           "    greet(\"hi\")\n    print(xs.len(), s.len, \"abc\".len, t)\n")
    assert messages(src) == []


def test_generic_struct_literal_infers_arguments():
    src = ("struct Pair[A, B]:\n    first: A\n    second: B\n\n"
           "fn main():\n    p = Pair{ first: 1, second: \"a\" }\n    print(p.first, p.second)\n")
    assert messages(src) == []


@pytest.mark.skipif(not HAS_CC, reason="no C toolchain")
def test_conversions_run(tmp_path):
    src = ("fn label() -> string:\n    return \"ok\"\n\n"
           "fn main():\n    a: i32 = 3\n    b: i64 = 10\n    names = List[string]()\n    names.push(\"x\")\n"
           "    names.push(label())\n    total: usize = 0\n    for i in 0..4:\n        total += i\n"
           "    f: f32 = 1.5\n    print(a + b, names.len(), names[1], total, f * 2.0)\n")
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["13", "2", "ok", "6", "3"]
