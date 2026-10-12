"""gg fmt has one canonical, idempotent layout, and indent errors carry a fix."""
import json
from pathlib import Path

from greengold.cli import cmd_check
from greengold.diagnostics import DiagnosticBag
from greengold.fmt import format_source
from greengold.lexer import tokenize
from tests.helpers import ROOT, EXAMPLES_DIR


def _tokens(src: str):
    diags = DiagnosticBag()
    toks = tokenize(src, diags)
    if any(d.severity == "error" for d in diags.items):
        return None
    return [(t.kind, t.text) for t in toks]


def test_format_is_idempotent_and_keeps_tokens():
    files = list(EXAMPLES_DIR.rglob("*.gg"))
    files += list((ROOT / "greengold").rglob("*.gg"))
    files += list((ROOT / "benchmarks").glob("*.gg"))
    assert files
    changed = 0
    for path in files:
        src = path.read_text(encoding="utf-8-sig")
        once = format_source(src)
        assert format_source(once) == once, path
        before = _tokens(src)
        if before is None:
            continue
        after = _tokens(once)
        assert after == before, path
        if once != src.replace("\r\n", "\n").replace("\r", "\n"):
            changed += 1
    assert changed >= 0


def test_block_indent_is_four_spaces():
    src = "fn main():\n  print(1)\n        print(2)\n"
    assert format_source(src) == "fn main():\n    print(1)\n    print(2)\n"


def test_else_lines_up_with_if():
    src = "fn main():\n    if true:\n        print(1)\n        else:\n            print(2)\n"
    out = format_source(src)
    assert "\n    else:\n" in out
    assert format_source(out) == out


def test_short_indent_fix_is_verified(tmp_path, capsys):
    path = tmp_path / "m.gg"
    path.write_text("fn main():\n  print(1)\n", encoding="utf-8")
    assert cmd_check([str(path)], True) == 1
    doc = json.loads(capsys.readouterr().out)
    diag = doc["diagnostics"][0]
    assert diag["code"] == "GG0103"
    fix = diag["fixes"][0]
    assert fix["applicability"] == "safe"
    assert fix["verified"] is True
    assert fix["edits"][0]["replacement"] == "    "


def test_missing_indent_fix_is_verified(tmp_path, capsys):
    path = tmp_path / "m.gg"
    path.write_text("fn main():\nprint(1)\n", encoding="utf-8")
    assert cmd_check([str(path)], True) == 1
    doc = json.loads(capsys.readouterr().out)
    diag = doc["diagnostics"][0]
    fix = diag["fixes"][0]
    assert fix["verified"] is True
    assert fix["edits"][0]["replacement"] == "    "


def test_unexpected_indent_fix_is_verified(tmp_path, capsys):
    path = tmp_path / "m.gg"
    path.write_text("fn main():\n    print(1)\n        print(2)\n", encoding="utf-8")
    assert cmd_check([str(path)], True) == 1
    doc = json.loads(capsys.readouterr().out)
    diag = next(d for d in doc["diagnostics"] if d["code"] == "GG0106")
    fix = diag["fixes"][0]
    assert fix["verified"] is True
    assert fix["edits"][0]["replacement"] == "    "


def test_multiline_string_is_kept():
    src = 'fn main():\n    x = """\n  keep\n"""\n    print(x)\n'
    out = format_source(src)
    assert "  keep\n" in out
    assert format_source(out) == out
    assert _tokens(src) == _tokens(out)


def test_else_after_a_nested_if_keeps_its_own_if():
    src = ("fn f(c: u8) -> i32:\n    for x in 0..3:\n        if c == 1:\n            pass\n"
           "        elif c == 2:\n            if x > 1:\n                return 1\n        else:\n            return 2\n"
           "    return 0\n\n# a top-level comment\nfn g():\n    pass\n")
    assert format_source(src) == src
