import pytest

from greengold.ast_nodes import (
    Assign, Binary, BorrowExpr, Call, ExprStmt, FieldAccess, For, FuncDecl, If, IntLit,
    MethodCall, Name, StructDecl, StructLit, Unary, VarDecl, While, dump_ast,
)
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse


def parse_src(src: str):
    diags = DiagnosticBag()
    prog = parse(tokenize(src, diags), diags)
    return prog, diags.items


def parse_ok(src: str):
    prog, errs = parse_src(src)
    assert not errs, [e.message for e in errs]
    return prog


def main_body(body: str):
    prog = parse_ok("fn main():\n" + "".join(f"    {l}\n" for l in body.strip().splitlines()))
    return prog.decls[0].body


def expr_of(text: str):
    stmt = main_body(f"x = {text}")[0]
    assert isinstance(stmt, VarDecl)
    return stmt.value


def test_var_decl_forms():
    body = main_body("a = 1\nb: i32 = 2\nfixed c = 3\nfixed d: i64 = 4")
    assert [(s.name, s.mutable, s.type_ref is not None) for s in body] == [
        ("a", True, False), ("b", True, True), ("c", False, False), ("d", False, True)]


def test_stored_reference_parses():
    body = main_body("fixed r: read P = hero\nw: lend P = hero\nr2 = read hero\nw2 = lend hero")
    assert body[0].ref_mode == "read" and not body[0].mutable
    assert body[1].ref_mode == "lend" and body[1].mutable
    assert isinstance(body[2].value, BorrowExpr) and body[2].value.mode == "read"
    assert isinstance(body[3].value, BorrowExpr) and body[3].value.mode == "lend" and body[3].mutable


def test_precedence_mul_over_add():
    e = expr_of("1 + 2 * 3")
    assert isinstance(e, Binary) and e.op == "+"
    assert isinstance(e.right, Binary) and e.right.op == "*"


def test_left_associative():
    e = expr_of("10 - 3 - 2")
    assert e.op == "-" and isinstance(e.left, Binary) and isinstance(e.right, IntLit)


def test_parentheses():
    e = expr_of("(1 + 2) * 3")
    assert e.op == "*" and isinstance(e.left, Binary) and e.left.op == "+"


def test_logic_precedence():
    e = expr_of("a or b and not c == d")
    assert e.op == "or" and e.right.op == "and"
    assert isinstance(e.right.right, Unary) and e.right.right.operand.op == "=="


def test_unary_minus_binds_tight():
    e = expr_of("-a * b")
    assert e.op == "*" and isinstance(e.left, Unary)


def test_struct_decl():
    prog = parse_ok("struct P:\n    x: f32\n    y: f32\n")
    d = prog.decls[0]
    assert isinstance(d, StructDecl) and [f.name for f in d.fields] == ["x", "y"]


def test_func_and_method_decl():
    prog = parse_ok(
        "fn add(a: i32, b: i32) -> i32:\n    return a + b\n"
        "impl P:\n    fn hit(self: lend P, n: i32):\n        self.h -= n\n"
        "fn show(g: consume P):\n    return\n")
    add, hit, show = prog.decls
    assert isinstance(add, FuncDecl) and add.ret.name == "i32"
    assert hit.owner == "P" and hit.name == "hit" and hit.params[0].mode == "lend"
    assert show.params[0].mode == "consume" and add.params[0].mode == ""


def test_direct_method_rejected():
    prog, errs = parse_src("fn P.hit(self: lend P, n: i32):\n    self.h -= n\n")
    assert any("Direct method declaration `fn P.hit` is not supported" in e.message for e in errs)


def test_struct_literal_multiline_without_commas():
    body = main_body("p = P{\n    x: 1.0\n    y: 2.0\n}")
    lit = body[0].value
    assert isinstance(lit, StructLit) and [f.name for f in lit.fields] == ["x", "y"]


def test_struct_literal_with_commas_and_trailing_comma():
    lit = main_body("p = P{ x: 1.0, y: 2.0, }")[0].value
    assert [f.name for f in lit.fields] == ["x", "y"]


def test_struct_literal_multiline_with_commas():
    lit = main_body("p = P{\n    x: 1.0,\n    y: 2.0,\n}")[0].value
    assert len(lit.fields) == 2


def test_call_args_are_plain_expressions():
    stmt = main_body("heal(p.a.b, 10)\nuse(q)")[0]
    call = stmt.expr
    assert isinstance(call, Call)
    assert isinstance(call.args[0], FieldAccess)


def test_method_call():
    stmt = main_body("player.take_damage(25)")[0]
    assert isinstance(stmt, ExprStmt) and isinstance(stmt.expr, MethodCall)


def test_assign_ops():
    body = main_body("x = 0\nx = 1\nx += 2\nx -= 3\nx *= 4\nx /= 5")
    assert isinstance(body[0], VarDecl)
    assert all(isinstance(s, Assign) for s in body[1:])
    assert [s.op for s in body[1:]] == ["=", "+=", "-=", "*=", "/="]


def test_if_elif_else():
    body = main_body("if a:\n    return\nelif b:\n    return\nelse:\n    return")
    node = body[0]
    assert isinstance(node, If) and len(node.branches) == 2 and node.else_body


def test_for_exclusive_and_inclusive():
    body = main_body("for i in 0..n:\n    print(i)\nfor j in 0..=n:\n    print(j)")
    assert isinstance(body[0], For) and not body[0].inclusive
    assert body[1].inclusive


def test_while_break_continue():
    body = main_body("while true:\n    break\n    continue")
    assert isinstance(body[0], While) and len(body[0].body) == 2


@pytest.mark.parametrize("src,msg", [
    ("fn main():\n    x: read = y\n", "Expected type name"),
    ("struct P:\n    a: lend Q\n", "`tied to`"),
    ("fn main():\n    x = consume 5\n", "parameter definition"),
    ("fn main():\n    x = \n", "Expected expression"),
    ("fn main():\n    if a:\n        return\n    else if b:\n        return\n", "elif"),
    ("x = 5\n", "top-level"),
    ("fn main():\n    x := 5\n", "`:=` was removed"),
    ("const N := 5\nfn main():\n    pass\n", "`:=` was removed"),
])
def test_parse_errors(src, msg):
    _, errs = parse_src(src)
    assert any(msg in e.message for e in errs), [e.message for e in errs]


def test_multiple_parse_errors_reported():
    src = "fn main():\n    x = \n    y = 5\n    z = (\n    w = 1 2\n"
    _, errs = parse_src(src)
    assert len(errs) >= 2


def test_dump_ast_runs():
    prog = parse_ok("fn main():\n    x = 1 + 2\n")
    assert "Binary" in dump_ast(prog)
