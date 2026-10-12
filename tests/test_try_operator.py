"""postfix `?` operator (restricted positions)."""
import pytest

from greengold.ast_nodes import ExprStmt, Try, VarDecl
from greengold.cli import compile_to_ir
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse

from .helpers import HAS_CC, messages, run_example, run_gg_source

needs_cc = pytest.mark.skipif(not HAS_CC, reason="gcc/clang not found")

PRE = """\
fn digit(c: u8) -> Result[i32, str]:
    if c >= '0' and c <= '9':
        return Ok(i32(c - '0'))
    return Err("bad")

fn first(a: []i32) -> Optional[i32]:
    if a.len == 0:
        return None
    return Valid(a[0])

"""


def has(msgs: list[str], text: str) -> bool:
    return any(text in m for m in msgs)


def parse_src(src: str):
    diags = DiagnosticBag()
    prog = parse(tokenize(src, diags), diags)
    return prog, [d.message for d in diags.items]


def in_fn(body: str, sig: str = "fn f(c: u8) -> Result[i32, string]:") -> str:
    lines = "".join(f"    {l}\n" if l.strip() else "\n" for l in body.strip("\n").splitlines())
    return PRE + sig + "\n" + lines + "\nfn main():\n    pass\n"


# ---------------------------------------------------------------- lexer / parser

def test_lexer_question_token():
    kinds = [t.kind for t in tokenize("a?\n", DiagnosticBag())]
    assert "?" in kinds


def test_parse_try_in_decl_and_stmt():
    prog, errs = parse_src("fn f():\n    x = g()?\n    g()?\n")
    assert not errs
    body = prog.decls[0].body
    assert isinstance(body[0], VarDecl) and isinstance(body[0].value, Try)
    assert isinstance(body[1], ExprStmt) and isinstance(body[1].expr, Try)


def test_parse_try_chain_and_method():
    prog, errs = parse_src("fn f():\n    x = a.b(1)?\n")
    assert not errs
    assert isinstance(prog.decls[0].body[0].value, Try)


def test_parse_bare_name_try_statement_ok():
    _, errs = parse_src("fn f():\n    x?\n")
    assert not errs


# ---------------------------------------------------------------- positive type checking

def test_ok_decl_assign_return_forms():
    src = in_fn("""\
x = digit(c)?
y: i32 = digit(c)?
y = digit(c)?
digit(c)?
return Ok(x + y)""")
    assert messages(src) == []


def test_ok_return_try_with_nested_result_type():
    src = PRE + """\
fn inner() -> Result[Result[i32, str], str]:
    return Ok(Ok(1))

fn outer() -> Result[i32, str]:
    return inner()?

fn main():
    pass
"""
    assert messages(src) == []


def test_ok_optional_try():
    src = in_fn("a = [1, 2]\nx = first(a)?\nreturn Valid(x)", "fn f() -> Optional[i32]:")
    assert messages(src) == []


def test_ok_different_ok_type_same_error_type():
    src = in_fn("x = digit(c)?\nreturn Ok(true)", "fn f(c: u8) -> Result[bool, str]:")
    assert messages(src) == []


def test_ok_try_inside_loop_and_branch():
    src = in_fn("""\
total = 0
for i in 0..3:
    if i == 1:
        v = digit(c)?
        print(v)
return Ok(total)""")
    assert messages(src) == []


def test_ok_try_in_generic_function():
    src = """\
fn pass_on[T](r: Result[T, str]) -> Result[T, str]:
    v = r?
    return Ok(v)

fn main():
    r: Result[i32, str] = Ok(1)
    print(pass_on(r).value_or_panic())
"""
    assert messages(src) == []


# ---------------------------------------------------------------- errors

def test_err_nested_position_call_arg():
    assert has(messages(in_fn("print(digit(c)?)\nreturn Ok(1)")), "`?` can only be used on the whole expression")


def test_err_nested_position_binary():
    assert has(messages(in_fn("x = digit(c)? + 1\nreturn Ok(x)")), "`?` can only be used on the whole expression")


def test_err_nested_try_in_operand():
    assert has(messages(in_fn("x = digit(u8(digit(c)?))?\nreturn Ok(x)")), "`?` can only be used on the whole expression")


def test_err_compound_assignment():
    assert has(messages(in_fn("x = 0\nx += digit(c)?\nreturn Ok(x)")), "`?` can only be used on the whole expression")


def test_err_condition_position():
    assert has(messages(in_fn("if digit(c)? > 0:\n    pass\nreturn Ok(1)")), "`?` can only be used on the whole expression")


def test_err_wrong_return_type_function():
    msgs = messages(in_fn("x = digit(c)?\nreturn x", "fn f(c: u8) -> i32:"))
    assert has(msgs, "must have return type Result[_, str], currently i32")


def test_err_function_without_return_type():
    msgs = messages(in_fn("digit(c)?", "fn f(c: u8):"))
    assert has(msgs, "must have return type Result[_, str], currently none")


def test_err_try_in_main():
    src = PRE + "fn main():\n    x = digit('1')?\n"
    assert has(messages(src), "must have return type Result[_, str]")


def test_err_result_in_optional_function():
    msgs = messages(in_fn("x = digit(c)?\nreturn Valid(x)", "fn f(c: u8) -> Optional[i32]:"))
    assert has(msgs, "cannot mix Result and Optional")


def test_err_optional_in_result_function():
    msgs = messages(in_fn("a = [1]\nx = first(a)?\nreturn Ok(x)"))
    assert has(msgs, "cannot mix Result and Optional")


def test_err_error_type_mismatch():
    msgs = messages(in_fn("x = digit(c)?\nreturn Ok(x)", "fn f(c: u8) -> Result[i32, i32]:"))
    assert has(msgs, "error types do not match")


def test_err_operand_not_result_or_optional():
    assert has(messages(in_fn("x = 5?\nreturn Ok(x)")), "can only be applied to Result or Optional")


def test_err_try_on_user_enum():
    src = "enum E:\n    A\n    B\n\nfn f() -> Result[i32, string]:\n    e = E.A\n    e?\n    return Ok(1)\n\nfn main():\n    pass\n"
    assert has(messages(src), "can only be applied to Result or Optional")


def test_err_try_result_type_mismatch_with_declared():
    src = in_fn("x: bool = digit(c)?\nreturn Ok(1)")
    assert has(messages(src), "mismatch")



def test_err_try_in_const():
    src = PRE + "const X: i32 = digit('1')?\n\nfn main():\n    pass\n"
    assert messages(src)


# ---------------------------------------------------------------- move analysis

def test_move_try_early_return_does_not_affect_following():
    src = """\
struct P:
    n: i32

fn eat(p: consume P):
    pass

fn g() -> Result[i32, string]:
    return Ok(1)

fn f() -> Result[i32, string]:
    p = P{ n: 1 }
    x = g()?
    eat(p)
    return Ok(x)

fn main():
    pass
"""
    assert messages(src) == []


def test_move_after_give_still_reported_with_try():
    src = """\
struct P:
    n: i32

fn eat(p: consume P):
    pass

fn g() -> Result[i32, string]:
    return Ok(1)

fn f() -> Result[i32, string]:
    p = P{ n: 1 }
    eat(p)
    x = g()?
    print(p.n)
    return Ok(x)

fn main():
    pass
"""
    assert has(messages(src), "was moved") or has(messages(src), "moved")



# ---------------------------------------------------------------- IR output / end-to-end

def test_codegen_result_try_shape():
    c = compile_to_ir(in_fn("x = digit(c)?\nreturn Ok(x)"))
    assert "Result_i32__str_" in c and "Result_i32__string_" in c


def test_codegen_optional_try_shape():
    c = compile_to_ir(in_fn("a = [1]\nx = first(a)?\nreturn Valid(x)", "fn f() -> Optional[i32]:"))
    assert "Optional_i32" in c


@needs_cc
def test_e2e_result_example_with_try():
    r = run_example("result.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().split("\n") == ["7", "not a digit"]


@needs_cc
def test_e2e_optional_try_and_different_payload(tmp_path):
    src = """\
fn first(a: []i32) -> Optional[i32]:
    if a.len == 0:
        return None
    return Valid(a[0])

fn is_big(a: []i32) -> Optional[bool]:
    x = first(a)?
    return Valid(x > 10)

fn show(o: Optional[bool]):
    match o:
        Valid(b):
            print(b)
        None:
            print(-1)

fn main():
    big = [50, 1]
    small = [3]
    show(is_big(big))
    show(is_big(small))
    show(is_big(big[0..0]))
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["true", "false", "-1"]


@needs_cc
def test_e2e_try_in_loop_returns_early(tmp_path):
    src = """\
fn digit(c: u8) -> Result[i32, string]:
    if c >= '0' and c <= '9':
        return Ok(i32(c - '0'))
    return Err("bad")

fn sum(s: [4]u8) -> Result[i32, string]:
    t = 0
    for i in 0..4:
        t += digit(s[i])?
    return Ok(t)

fn main():
    match sum(['1', '2', '3', '4']):
        Ok(v):
            print(v)
        Err(e):
            print(e)
"""
    r = run_gg_source(tmp_path, src)
    # `t += f()?` compound assignment forbidden
    assert r.returncode != 0
    assert "can only be used on the whole expression" in r.stderr


@needs_cc
def test_e2e_try_in_loop_valid_form(tmp_path):
    src = """\
fn digit(c: u8) -> Result[i32, str]:
    if c >= '0' and c <= '9':
        return Ok(i32(c - '0'))
    return Err("bad")

fn sum(s: [4]u8) -> Result[i32, str]:
    t = 0
    for i in 0..4:
        d = digit(s[i])?
        t += d
    return Ok(t)

fn main():
    match sum(['1', '2', '3', '4']):
        Ok(v):
            print(v)
        Err(e):
            print(e)
    match sum(['1', 'x', '3', '4']):
        Ok(v):
            print(v)
        Err(e):
            print(e)
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["10", "bad"]
