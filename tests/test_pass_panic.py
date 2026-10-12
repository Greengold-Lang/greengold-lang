"""`pass` statement and `panic` builtin function."""
import pytest

from greengold.cli import compile_to_ir
from greengold.ast_nodes import Pass
from greengold.lexer import tokenize
from greengold.diagnostics import DiagnosticBag
from greengold.parser import parse

from .helpers import HAS_CC, messages, run_gg_source

needs_cc = pytest.mark.skipif(not HAS_CC, reason="gcc/clang not found")



def test_lexer_pass_keyword():
    toks = tokenize("pass\n", DiagnosticBag())
    assert toks[0].kind == "pass"


def test_parser_pass_in_every_block():
    src = """fn main():
    if true:
        pass
    elif false:
        pass
    else:
        pass
    while false:
        pass
    for i in 0..3:
        pass
"""
    diags = DiagnosticBag()
    prog = parse(tokenize(src, diags), diags)
    assert not diags.items
    body = prog.decls[0].body
    assert isinstance(body[0].branches[0].body[0], Pass)
    assert isinstance(body[0].else_body[0], Pass)
    assert isinstance(body[1].body[0], Pass)
    assert isinstance(body[2].body[0], Pass)


def test_pass_typechecks_in_fn_body():
    assert messages("fn f():\n    pass\n\nfn main():\n    f()\n") == []


def test_pass_codegen_empty_statement():
    compile_to_ir("fn main():\n    if true:\n        pass\n")


def test_panic_typechecks_and_terminates_return_analysis():
    src = """fn f(x: i32) -> i32:
    if x > 0:
        return 1
    else:
        panic("negatif")

fn main():
    print(f(1))
"""
    assert messages(src) == []


def test_panic_as_whole_body_counts_as_return():
    assert messages('fn f() -> i32:\n    panic("hep")\n\nfn main():\n    print(f())\n') == []


def test_missing_return_still_reported_without_panic():
    src = "fn f(x: i32) -> i32:\n    if x > 0:\n        return 1\n\nfn main():\n    print(f(1))\n"
    assert any("not all paths have a `return`" in m for m in messages(src))


def test_panic_non_literal_error():
    msgs = messages('fn main():\n    panic(5)\n')
    assert any("expects a `str` or `string` message, found `i32`" in m for m in msgs)


def test_panic_accepts_str_variable_and_fstring():
    assert messages('fn main():\n    s = "x"\n    panic(s)\n') == []
    assert messages('fn main():\n    n = 3\n    panic(f"bad {n}")\n') == []


def test_panic_wrong_arg_count():
    assert any("expects exactly 1 argument" in m for m in messages('fn main():\n    panic()\n'))


def test_panic_has_no_value():
    msgs = messages('fn main():\n    x = panic("a")\n')
    assert any("does not return a value" in m for m in msgs)


def test_panic_name_reserved():
    msgs = messages("fn panic():\n    pass\n\nfn main():\n    pass\n")
    assert any("is a reserved name" in m for m in msgs)


def test_panic_codegen():
    ir = compile_to_ir('fn main():\n    panic("kaboom")\n', filename="a.gg")
    assert 'c"kaboom\\00"' in ir and 'c"a.gg\\00"' in ir and "i32 2, i32 5) noreturn" in ir


def test_move_analysis_after_panic_branch():
    src = """struct S:
    v: i32

fn eat(s: consume S):
    print(s.v)

fn main():
    s = S{ v: 1 }
    if s.v > 5:
        eat(s)
        panic("bitti")
    print(s.v)
"""
    assert messages(src) == []


@needs_cc
def test_e2e_panic_exit_code_and_message(tmp_path):
    src = 'fn main():\n    print(1)\n    panic("kaboom")\n'
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 101
    assert r.stdout.splitlines() == ["1"]
    assert "Runtime error: kaboom" in r.stderr
    assert "a.gg:3:5" in r.stderr



@needs_cc
def test_e2e_panic_also_in_release(tmp_path):
    r = run_gg_source(tmp_path, 'fn main():\n    panic("x")\n', release=True)
    assert r.returncode == 101


@needs_cc
def test_e2e_pass_runs(tmp_path):
    src = """fn main():
    n = 0
    for i in 0..4:
        if i == 2:
            pass
        else:
            n += 1
    print(n)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["3"]
