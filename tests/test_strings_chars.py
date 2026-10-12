"""String operations and char literals."""
from pathlib import Path
import subprocess
import sys
import pytest

from greengold.cli import compile_to_ir
from tests.helpers import run_built, EXAMPLES_DIR
from greengold.diagnostics import CompileError

ROOT = Path(__file__).resolve().parent.parent


def run_prog(src: str, release: bool = False) -> subprocess.CompletedProcess[str]:
    return run_built(src, release=release)



def must_fail(src: str, text: str):
    with pytest.raises(CompileError) as exc_info:
        compile_to_ir(src)
    msgs = [d.message for d in exc_info.value.diagnostics]
    assert any(text in m for m in msgs), f"Expected `{text}` not in error messages: {msgs}"



def test_strings_acceptance():
    src = (EXAMPLES_DIR / "strings.gg").read_text(encoding="utf-8")
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == ["2", "82", "true", "65"]


def test_char_literal_values_and_escapes():
    src = """
fn main():
    c1 = 'A'
    c2 = '\\n'
    c3 = '\\t'
    c4 = '\\r'
    c5 = '\\\\'
    c6 = '\\''
    c7 = '\\"'
    c8 = '\\0'
    print(c1)
    print(c2)
    print(c3)
    print(c4)
    print(c5)
    print(c6)
    print(c7)
    print(c8)
"""
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == [
        "65",
        "10",
        "9",
        "13",
        "92",
        "39",
        "34",
        "0",
    ]


def test_char_literal_errors():
    must_fail("fn main():\n    c = ''\n", "Empty char literal")
    must_fail("fn main():\n    c = 'abc'\n", "Char literal can only contain a single character")
    must_fail("fn main():\n    c = 'é'\n", "Char literal cannot contain multi-byte UTF-8 character")
    must_fail("fn main():\n    c = '\\a'\n", "Unknown escape sequence")


def test_string_escapes_and_nul_rejection():
    # \\0 is forbidden in string literals
    must_fail('fn main():\n    s = "hello\\0world"\n', "\\0")
    # unknown escape in string
    must_fail('fn main():\n    s = "hello\\a"\n', "Unknown escape sequence")


def test_string_equality():
    src = """
fn main():
    s1 = "hello"
    s2 = "hello"
    s3 = "world"
    s4 = "hell"
    s5 = ""
    s6 = ""
    print(s1 == s2)
    print(s1 != s2)
    print(s1 == s3)
    print(s1 == s4)
    print(s5 == s6)
    print(s1 != s5)
"""
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == ["true", "false", "false", "false", "true", "true"]


def test_string_len_and_indexing():
    src = """
const G = "Relang"

fn main():
    print(G.len)
    print(G[0])
    print(G[5])
    s = "Test"
    print(s.len)
    print(s[0])
    print(s[3])
"""
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == ["6", "82", "103", "4", "84", "116"]


def test_string_bounds_panic_debug():
    src = """
fn main():
    s = "Re"
    i: i32 = 5
    print(s[i])
"""
    res = run_prog(src, release=False)
    assert res.returncode == 101
    assert "array index out of bounds (index 5, length 2)" in res.stderr


def test_string_negative_bounds_panic():
    src = """
fn main():
    s = "Re"
    i: i32 = -1
    print(s[i])
"""
    res = run_prog(src, release=False)
    assert res.returncode == 101
    assert "array index out of bounds (index -1, length 2)" in res.stderr


def test_string_constant_index_out_of_bounds_compile_error():
    must_fail('fn main():\n    s = "Re"\n    print("Re"[5])\n', "out of bounds")
    must_fail('fn main():\n    s = "Re"\n    print("Re"[-1])\n', "cannot be negative")


def test_string_immutability():
    must_fail('fn main():\n    s = "hello"\n    s[0] = 65\n', "Cannot assign to string characters")
    must_fail('fn f(x: lend u8):\n    return\nfn main():\n    s = "hello"\n    f(s[0])\n', "Cannot `lend` string character")
    must_fail('fn f(s: []u8):\n    return\nfn main():\n    s = "hello"\n    f(s[1..3])\n', "expected `[]u8`, found `str`")


def test_string_give_rejected():
    must_fail('fn f(s: consume str):\n    return\nfn main():\n    return\n', "str is copied, `consume` is not needed")



def test_string_in_struct():
    src = """
struct Item:
    name: str
    code: u8

fn main():
    item = Item{ name: "Sword", code: 'S' }
    print(item.name)
    print(item.name.len)
    print(item.name[0])
    print(item.code)
"""
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == ["Sword", "5", "83", "83"]


def test_lend_string_variable():
    src = """
fn change(s: lend str):
    s = "world"

fn main():
    s = "hello"
    print(s)
    change(s)
    print(s)
"""
    res = run_prog(src)
    assert res.returncode == 0
    lines = res.stdout.strip().splitlines()
    assert lines == ["hello", "world"]
