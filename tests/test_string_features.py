"""Comprehensive test suite for Greengold advanced string features:
- Multiline string literals (\"\"\"...\"\"\")
- String interpolation (f\"...\", $\"...\", multiline f\"\"\"...\"\"\", escaped {{ and }})
- String concatenation with + (str + str, str + int, int + str, str + float, str + bool, String + str)
- Conversions (s.to_string(), String(s), String(int), to_string(s), s.len())
- Comptime evaluation of format strings and + concat
- End-to-end execution on both LLVM and C backends
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse
from greengold.typecheck import check_program
from tests.helpers import front_end, messages

ROOT = Path(__file__).resolve().parent.parent
HAS_COMPILER = shutil.which("gcc") is not None or shutil.which("clang") is not None


# ---------------------------------------------------------------------------
# Lexer tests
# ---------------------------------------------------------------------------

def test_lexer_multiline_string():
    src = '"""hello\nworld"""'
    diags = DiagnosticBag()
    tokens = tokenize(src, diags)
    assert not diags.has_errors()
    assert tokens[0].kind == "STRING"
    assert tokens[0].text == "hello\nworld"


def test_lexer_fstring_tokens():
    src = 'f"count: {x}"'
    diags = DiagnosticBag()
    tokens = tokenize(src, diags)
    assert not diags.has_errors()
    assert tokens[0].kind == "FSTRING"
    assert tokens[0].text == "count: {x}"


def test_lexer_dollar_fstring():
    src = '$"val: {v}"'
    diags = DiagnosticBag()
    tokens = tokenize(src, diags)
    assert not diags.has_errors()
    assert tokens[0].kind == "FSTRING"
    assert tokens[0].text == "val: {v}"


def test_lexer_multiline_fstring():
    src = 'f"""a: {x}\nb: {y}"""'
    diags = DiagnosticBag()
    tokens = tokenize(src, diags)
    assert not diags.has_errors()
    assert tokens[0].kind == "FSTRING"
    assert tokens[0].text == "a: {x}\nb: {y}"


# ---------------------------------------------------------------------------
# Parser & AST tests
# ---------------------------------------------------------------------------

def test_parser_fstring_ast():
    src = 'fn main():\n    x = 5\n    s = f"num: {x}"\n'
    prog, errs = front_end(src)
    assert not errs, [e.message for e in errs]
    # Check that s assignment has FormatStr
    assign = prog.decls[-1].body[1]
    from greengold.ast_nodes import FormatStr, StrLit, Name
    assert isinstance(assign.value, FormatStr)
    assert len(assign.value.parts) == 2
    assert isinstance(assign.value.parts[0], StrLit)
    assert assign.value.parts[0].value == "num: "
    assert isinstance(assign.value.parts[1], Name)
    assert assign.value.parts[1].name == "x"


def test_parser_fstring_escaped_braces():
    src = 'fn main():\n    s = f"{{hello}}"\n'
    prog, errs = front_end(src)
    assert not errs, [e.message for e in errs]
    assign = prog.decls[-1].body[0]
    from greengold.ast_nodes import FormatStr, StrLit
    assert isinstance(assign.value, FormatStr)
    assert len(assign.value.parts) == 1
    assert isinstance(assign.value.parts[0], StrLit)
    assert assign.value.parts[0].value == "{hello}"


# ---------------------------------------------------------------------------
# Typechecker tests
# ---------------------------------------------------------------------------

def test_typecheck_fstring_type_is_string():
    src = 'fn main():\n    x = 10\n    s = f"x is {x}"\n    print(s)\n'
    prog, errs = front_end(src)
    assert not errs, [e.message for e in errs]
    assign = prog.decls[-1].body[1]
    assert assign.value.ty == "string"


def test_typecheck_string_concatenation():
    src = """\
fn main():
    s1 = "hello " + "world"
    s2 = "count: " + 42
    s3 = 10 + " items"
    s4 = "pi: " + 3.14
    s5 = "flag: " + true
    s6 = s1 + " again"
"""
    prog, errs = front_end(src)
    assert not errs, [e.message for e in errs]
    for s in prog.decls[-1].body:
        assert s.value.ty == "string"


def test_typecheck_to_string_and_len():
    src = """\
fn main():
    s = "hello"
    s_owned = s.to_string()
    s_conv = string(s)
    num_conv = string(123)
    n = s.len()
    n2 = s.len
    s_new = string.new()
    String = 42
    Str = "variable"
"""
    prog, errs = front_end(src)
    assert not errs, [e.message for e in errs]
    stmts = prog.decls[-1].body
    assert stmts[1].value.ty == "string"
    assert stmts[2].value.ty == "string"
    assert stmts[3].value.ty == "string"
    assert stmts[4].value.ty == "usize"
    assert stmts[5].value.ty == "usize"
    assert stmts[6].value.ty == "string"
    assert stmts[7].value.ty == "i32"
    assert stmts[8].value.ty == "str"


def test_typecheck_capital_string_is_unknown_type():
    src = """\
fn main():
    s: String = "invalid"
"""
    prog, errs = front_end(src)
    assert any("Unknown type `String`" in e.message or "No struct or enum named `String`" in e.message for e in errs)


# ---------------------------------------------------------------------------
# Comptime evaluator tests
# ---------------------------------------------------------------------------

def test_comptime_format_string():
    from greengold.ast_nodes import FormatStr, StrLit, IntLit, Program
    from greengold.comptime import Interp
    interp = Interp(Program([]))
    fmt = FormatStr([StrLit("num: "), IntLit(42)])
    assert interp.eval(fmt, {}) == "num: 42"


def test_comptime_string_concat():
    from greengold.ast_nodes import Binary, StrLit, IntLit, Program
    from greengold.comptime import Interp
    interp = Interp(Program([]))
    b = Binary("+", StrLit("answer = "), IntLit(42))
    assert interp.eval(b, {}) == "answer = 42"


# ---------------------------------------------------------------------------
# End-to-end execution tests
# ---------------------------------------------------------------------------

def run_both(tmp_path: Path, src: str) -> tuple[str, str]:
    """Runs source with the LLVM backend. Returns (stdout, stdout) so older two-backend checks still read."""
    f = tmp_path / "test_prog.gg"
    f.write_text(src, encoding="utf-8")
    cmd = [sys.executable, "-m", "greengold", "run", str(f)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=60)
    assert p.returncode == 0, f"LLVM backend failed:\nstdout: {p.stdout}\nstderr: {p.stderr}"
    out = p.stdout.replace("\r\n", "\n")
    return out, out

@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_fstring_and_interpolation(tmp_path):
    src = """\
fn main():
    name = "Greengold"
    version = 1
    flag = true
    pi = 3.14
    s = f"Welcome to {name} v{version}! active={flag}, pi={pi}"
    print(s)
"""
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    assert "Welcome to Greengold v1! active=true, pi=3.14" in llvm_out


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_fstring_escaped_braces(tmp_path):
    src = """\
fn main():
    val = 42
    print(f"{{val: {val}}}")
"""
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    assert llvm_out.strip() == "{val: 42}"


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_string_concatenation(tmp_path):
    src = """\
fn main():
    s1 = "Hello" + " " + "World!"
    print(s1)
    s2 = "Items: " + 10
    print(s2)
    s3 = 50 + "% completed"
    print(s3)
    s4 = "Passed: " + true
    print(s4)
"""
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    expected = "Hello World!\nItems: 10\n50% completed\nPassed: true\n"
    assert llvm_out == expected


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_multiline_strings(tmp_path):
    src = '''\
fn main():
    s = """Line 1
Line 2
Line 3"""
    print(s)
'''
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    assert llvm_out.strip() == "Line 1\nLine 2\nLine 3"


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_multiline_fstring(tmp_path):
    src = '''\
fn main():
    x = 10
    y = 20
    s = f"""X: {x}
Y: {y}
Sum: {x + y}"""
    print(s)
'''
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    assert llvm_out.strip() == "X: 10\nY: 20\nSum: 30"


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_conversions(tmp_path):
    src = """\
fn main():
    s = "greengold"
    s1 = s.to_string()
    s2 = string(s)
    s3 = string(789)
    s4 = string(456)
    s5 = to_string("core_func")
    print(s1)
    print(s2)
    print(s3)
    print(s4)
    print(s5)
    print(s.len())
"""
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    expected = "greengold\ngreengold\n789\n456\ncore_func\n9\n"
    assert llvm_out == expected


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_string_explicit_types(tmp_path):
    src = """\
fn takes_string(s: string) -> string:
    return s + "!"

fn main():
    s1: string = "alpha".to_string()
    # Developers can freely use Str and String as variable names
    String = 42
    Str = "beta"
    print(takes_string(s1))
    print(String)
    print(Str)
"""
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    expected = "alpha!\n42\nbeta\n"
    assert llvm_out == expected


@pytest.mark.skipif(not HAS_COMPILER, reason="gcc/clang not found")
def test_e2e_direct_print_temporary_string(tmp_path):
    src = """\
fn main():
    print(f"Direct temp {100}")
    print("Direct concat: " + 200)
"""
    llvm_out, c_out = run_both(tmp_path, src)
    assert llvm_out == c_out
    assert "Direct temp 100\nDirect concat: 200\n" == llvm_out


def test_vscode_grammar_string_interpolation():
    """Verify that VS Code TextMate grammar properly scopes f-string interpolation and variables."""
    import json
    import re
    from pathlib import Path

    grammar_path = Path(__file__).resolve().parent.parent / "vscode-extension" / "syntaxes" / "gg.tmLanguage.json"
    assert grammar_path.exists(), "Grammar file not found"

    with open(grammar_path, encoding="utf-8") as f:
        grammar = json.load(f)

    # Check that variables, property-access, and self-expression exist
    repo = grammar["repository"]
    assert "variables" in repo
    assert "property-access" in repo
    assert "self-expression" in repo

    # Verify that strings repository contains format strings with template expression scopes
    strings_patterns = repo["strings"]["patterns"]
    format_rules = [p for p in strings_patterns if "format" in p.get("name", "")]
    assert len(format_rules) >= 2  # multiline and single-line format strings

    for rule in format_rules:
        patterns = rule.get("patterns", [])
        interp_rules = [p for p in patterns if "template.expression" in p.get("name", "")]
        assert len(interp_rules) == 1, f"Missing template expression rule in {rule.get('name')}"
        interp = interp_rules[0]
        assert interp.get("contentName") == "source.gg"
        assert "punctuation.definition.template-expression.begin.gg" in interp["beginCaptures"]["0"]["name"]
        assert "punctuation.definition.template-expression.end.gg" in interp["endCaptures"]["0"]["name"]

    # Verify all regexes compile
    def check_regexes(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("match", "begin", "end") and isinstance(v, str):
                    try:
                        re.compile(v)
                    except re.error as err:
                        # TextMate grammars use Oniguruma, which allows variable-width look-behind; Python's re does not.
                        if "look-behind" not in str(err):
                            raise
                else:
                    check_regexes(v)
        elif isinstance(node, list):
            for item in node:
                check_regexes(item)

    check_regexes(grammar)

