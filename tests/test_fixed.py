"""Variables can be changed by default; `fixed` forbids changes; unchanged variables are inferred `fixed`."""
from pathlib import Path

import pytest

from greengold.ast_nodes import FuncDecl, VarDecl
from greengold.cli import load_sources_and_ast
from greengold.typecheck import check_program
from .helpers import HAS_CC, front_end, messages, run_built


def _main_decls(src: str) -> dict[str, VarDecl]:
    program, diags = front_end(src)
    assert not [d.message for d in diags]
    main = next(d for d in program.decls if isinstance(d, FuncDecl) and d.name == "main")
    return {s.name: s for s in main.body if isinstance(s, VarDecl)}


def test_variables_change_without_a_keyword():
    assert messages("fn main():\n    n = 0\n    n += 1\n    xs = List[i32]()\n    xs.push(n)\n") == []


def test_fixed_rejects_assign_lend_and_changing_methods():
    msgs = messages(
        "fn grow(xs: lend List[i32]):\n    xs.push(1)\n\n"
        "fn main():\n"
        "    fixed n = 0\n    n += 1\n"
        "    fixed xs = List[i32]()\n    xs.push(1)\n    grow(xs)\n"
    )
    assert any("`n` is declared `fixed`" in m for m in msgs)
    assert any("`push` changes `xs`" in m for m in msgs)
    assert any("`xs` cannot be `lend`ed" in m for m in msgs)


def test_fixed_destructure_and_reference():
    msgs = messages("struct P:\n    hp: i32\n\nfn main():\n"
                    "    fixed a, b = (1, 2)\n    a = 3\n"
                    "    p = P{ hp: 1 }\n    q = P{ hp: 2 }\n"
                    "    fixed r = lend p\n    r.hp = 5\n    r = q\n")
    assert any("`a` is declared `fixed`" in m for m in msgs)
    assert any("Cannot rebind `r`" in m for m in msgs)
    # writing through a `fixed` reference is allowed: only the binding is fixed
    assert not any("r.hp" in m for m in msgs)


def test_fixed_error_offers_to_delete_the_word():
    _, diags = front_end("fn main():\n    fixed n = 0\n    n = 1\n")
    fix = diags[0].fixes[0]
    edit = fix.edits[0]
    assert "Delete `fixed`" in fix.description
    assert (edit.start_line, edit.start_col, edit.end_col, edit.replacement) == (2, 5, 11, "")


def test_var_is_removed_with_a_fix():
    _, diags = front_end("fn main():\n    var n = 0\n    for var x in [1, 2]:\n        print(x)\n    print(n)\n")
    removed = [d for d in diags if "`var` was removed" in d.message]
    assert len(removed) == 2
    assert removed[0].code == "GG0132"
    edit = removed[0].fixes[0].edits[0]
    assert (edit.start_line, edit.start_col, edit.end_col, edit.replacement) == (2, 5, 9, "")


def test_top_level_var_points_to_const():
    _, diags = front_end("var LIMIT = 3\n\nfn main():\n    print(LIMIT)\n")
    assert diags and "`var` was removed" in diags[0].message and "const" in (diags[0].hint or "")


def test_unchanged_variables_are_inferred_fixed():
    decls = _main_decls(
        "fn add(xs: List[i32]):\n    xs.push(1)\n\n"
        "fn main():\n"
        "    a = 1\n    b = 2\n    b += a\n"
        "    xs = List[i32]()\n    add(xs)\n"
        "    ys = List[i32]()\n    print(ys.len)\n"
        "    fixed c = 3\n"
        "    out = List[i32]()\n    f = fn(x: i32) => out.push(x)\n    f(c)\n"
        "    zs = [1, 2]\n    for z in zs:\n        z += b\n"
    )
    auto = {name for name, d in decls.items() if getattr(d, "auto_fixed", False)}
    # `c` is written `fixed`, so it needs no hint
    assert auto == {"a", "ys", "f"}


def test_loop_variable_lends_when_the_body_changes_it():
    src = ("struct P:\n    hp: i32\n\nfn main():\n"
           "    xs = List[i32]()\n    xs.push(1)\n    xs.push(2)\n"
           "    for x in xs:\n        x *= 10\n"
           "    ps = [P{ hp: 1 }, P{ hp: 2 }]\n"
           "    for p in ps:\n        p.hp += 5\n"
           "    for x in xs:\n        print(x)\n"
           "    for p in ps:\n        print(p.hp)\n")
    assert messages(src) == []
    if HAS_CC:
        r = run_built(src)
        assert r.returncode == 0, r.stderr
        assert r.stdout.split() == ["10", "20", "6", "7"]


def test_loop_counter_and_string_bytes_stay_read_only():
    msgs = messages("fn main():\n    for i in 0..3:\n        i += 1\n    for c in \"ab\":\n        c += 1\n")
    assert any("loop counter" in m for m in msgs)
    assert any("byte of a `str`" in m for m in msgs)


def _check(path: Path) -> list[str]:
    program, _, diags = load_sources_and_ast([str(path)])
    if not diags.has_errors():
        check_program(program, diags, str(path))
    return [d.message for d in diags.items if not d.hidden]


def test_files_start_public(tmp_path: Path):
    (tmp_path / "shapes.gg").write_text(
        "struct Circle:\n    radius: f64\n\n"
        "fn area(c: Circle) -> f64:\n    return c.radius * c.radius\n\n"
        "private\n"
        "fn secret() -> i32:\n    return 1\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "shapes.gg"\n\n'
        "fn main():\n"
        "    c = shapes.Circle{ radius: 2.0 }\n"
        "    print(shapes.area(c), c.radius)\n"
        "    print(shapes.secret())\n",
        encoding="utf-8",
    )
    msgs = _check(main)
    assert not any("area" in m or "Circle" in m or "radius" in m for m in msgs)
    assert any("secret" in m and "private" in m for m in msgs)
