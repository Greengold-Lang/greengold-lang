from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize


def lex(src: str):
    diags = DiagnosticBag()
    toks = tokenize(src, diags)
    return toks, diags.items


def kinds(src: str) -> list[str]:
    toks, errs = lex(src)
    assert not errs, [e.message for e in errs]
    return [t.kind for t in toks]


def test_simple_statement():
    assert kinds("x = 5\n") == ["NAME", "=", "INT", "NEWLINE", "EOF"]


def test_keywords():
    assert kinds("var consume read lend\n")[:4] == ["var", "consume", "read", "lend"]
    assert kinds("comptime copy soa exclusive tied\n")[:5] == ["comptime", "copy", "soa", "exclusive", "tied"]


def test_own_give_are_plain_names():
    # `own`/`give` were removed from the language: they are now regular names.
    assert kinds("own give\n")[:2] == ["NAME", "NAME"]


def test_indent_dedent():
    src = "fn f():\n    return\nfn g():\n    return\n"
    ks = kinds(src)
    assert ks.count("INDENT") == 2
    assert ks.count("DEDENT") == 2
    assert ks[-1] == "EOF"


def test_nested_dedent_at_eof():
    src = "fn f():\n    if x:\n        return"
    ks = kinds(src)
    assert ks[-3:] == ["DEDENT", "DEDENT", "EOF"]
    assert ks.count("NEWLINE") == 3


def test_blank_and_comment_lines_ignored():
    src = "fn f():\n\n    # comment\n    return  # comment at end\n"
    ks = kinds(src)
    assert ks.count("INDENT") == 1
    assert ks.count("NEWLINE") == 2


def test_positions():
    toks, _ = lex("fn main():\n    x = 5\n")
    x = next(t for t in toks if t.text == "x")
    assert (x.line, x.col) == (2, 5)


def test_range_is_not_float():
    assert kinds("0..n\n")[:3] == ["INT", "..", "NAME"]
    assert kinds("0..=10\n")[:3] == ["INT", "..=", "INT"]


def test_float_literal():
    toks, _ = lex("1.5\n")
    assert toks[0].kind == "FLOAT" and toks[0].text == "1.5"


def test_braces_suppress_newlines_and_indent():
    src = "p = P{\n    x: 1\n    y: 2\n}\n"
    ks = kinds(src)
    assert "INDENT" not in ks and "DEDENT" not in ks
    assert ks.count("NEWLINE") == 1


def test_parens_suppress_newlines():
    ks = kinds("f(1,\n  2)\n")
    assert ks.count("NEWLINE") == 1


def test_string_escapes():
    toks, _ = lex('"a\\nb"\n')
    assert toks[0].kind == "STRING" and toks[0].text == "a\nb"


def test_two_char_operators():
    ks = kinds("a += b -> c <= d != e\n")
    assert "+=" in ks and "->" in ks and "<=" in ks and "!=" in ks


def test_tab_is_error():
    _, errs = lex("fn f():\n\treturn\n")
    assert any("Tab" in e.message for e in errs)


def test_double_slash_is_error():
    _, errs = lex("x = 5 // comment\n")
    assert any("// is not a comment, use # for comments." in e.message for e in errs)


def test_bad_indent_width():
    _, errs = lex("fn f():\n  return\n")
    assert errs


def test_unclosed_brace():
    _, errs = lex("x = P{ a: 1\n")
    assert any("never closed" in e.message for e in errs)


def test_unterminated_string():
    _, errs = lex('x = "abc\n')
    assert any("String" in e.message for e in errs)
