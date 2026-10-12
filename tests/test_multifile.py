from pathlib import Path
import pytest
from greengold.cli import cmd_run, compile_to_ir
from greengold.diagnostics import CompileError
from greengold.parser import parse
from greengold.lexer import tokenize
from greengold.diagnostics import DiagnosticBag
from greengold.ast_nodes import ImportDecl
from .helpers import HAS_CC


def test_import_ast_parsing():
    diags = DiagnosticBag()
    toks = tokenize('import "math_utils.gg"\nimport player\n', diags)
    assert not diags.has_errors()
    prog = parse(toks, diags)
    assert not diags.has_errors()
    assert len(prog.decls) == 2
    assert isinstance(prog.decls[0], ImportDecl)
    assert prog.decls[0].path == "math_utils.gg"
    assert isinstance(prog.decls[1], ImportDecl)
    assert prog.decls[1].path == "player.gg"


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_import_and_compile(tmp_path: Path):
    types_file = tmp_path / "models.gg"
    types_file.write_text(
        "public\n"
        "struct Hero:\n"
        "    name: str\n"
        "    hp: i32\n",
        encoding="utf-8"
    )

    main_file = tmp_path / "main.gg"
    main_file.write_text(
        'import "models.gg"\n\n'
        "fn main():\n"
        '    h = models.Hero{ name: "ReKnight", hp: 100 }\n'
        "    print(h.hp)\n",
        encoding="utf-8"
    )

    code = cmd_run([str(main_file)])
    assert code == 0


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_cli_multiple_files_without_import(tmp_path: Path):
    f1 = tmp_path / "calc.gg"
    f1.write_text(
        "public\n"
        "fn multiply(a: i32, b: i32) -> i32:\n"
        "    return a * b\n",
        encoding="utf-8"
    )

    f2 = tmp_path / "app.gg"
    f2.write_text(
        'import "calc.gg"\n\n'
        "fn main():\n"
        "    print(calc.multiply(6, 7))\n",
        encoding="utf-8"
    )

    # Extra files are not merged into the root. The root imports what it uses.
    code = cmd_run([str(f2)])
    assert code == 0


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_diamond_import(tmp_path: Path):
    common = tmp_path / "common.gg"
    common.write_text(
        "public\n"
        "const BASE_STAT: i32 = 10\n",
        encoding="utf-8"
    )

    mod_a = tmp_path / "mod_a.gg"
    mod_a.write_text(
        'import "common.gg"\n\n'
        "public\n"
        "fn get_a() -> i32:\n"
        "    return common.BASE_STAT + 1\n",
        encoding="utf-8"
    )

    mod_b = tmp_path / "mod_b.gg"
    mod_b.write_text(
        'import "common.gg"\n\n'
        "public\n"
        "fn get_b() -> i32:\n"
        "    return common.BASE_STAT + 2\n",
        encoding="utf-8"
    )

    main_file = tmp_path / "main.gg"
    main_file.write_text(
        'import "mod_a.gg"\n'
        'import "mod_b.gg"\n\n'
        "fn main():\n"
        "    print(mod_a.get_a() + mod_b.get_b())\n",
        encoding="utf-8"
    )

    code = cmd_run([str(main_file)])
    assert code == 0


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_circular_import(tmp_path: Path):
    circ_a = tmp_path / "circ_a.gg"
    circ_b = tmp_path / "circ_b.gg"

    circ_a.write_text(
        'import "circ_b.gg"\n\n'
        "public\n"
        "struct Alpha:\n"
        "    val: i32\n",
        encoding="utf-8"
    )

    circ_b.write_text(
        'import "circ_a.gg"\n\n'
        "public\n"
        "struct Beta:\n"
        "    num: i32\n",
        encoding="utf-8"
    )

    main_file = tmp_path / "main.gg"
    main_file.write_text(
        'import "circ_a.gg"\n'
        'import "circ_b.gg"\n\n'
        "fn main():\n"
        "    a = circ_a.Alpha{ val: 42 }\n"
        "    b = circ_b.Beta{ num: 24 }\n"
        "    print(a.val + b.num)\n",
        encoding="utf-8"
    )

    code = cmd_run([str(main_file)])
    assert code == 0


def test_import_not_found(tmp_path: Path):
    main_file = tmp_path / "main.gg"
    main_file.write_text(
        'import "missing.gg"\n\n'
        "fn main():\n"
        "    pass\n",
        encoding="utf-8"
    )

    with pytest.raises(CompileError) as exc_info:
        compile_to_ir(main_file.read_text(encoding="utf-8"), filename=str(main_file))
    errs = exc_info.value.diagnostics
    assert any("not found" in d.message for d in errs)


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_rpg_example_runs():
    rpg_main = Path(__file__).resolve().parent.parent / "examples" / "rpg" / "main.gg"
    assert rpg_main.exists()
    code = cmd_run([str(rpg_main)])
    assert code == 0
