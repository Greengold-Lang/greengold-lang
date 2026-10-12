"""Each file is a module: public by default, qualified names, one compilation."""
from pathlib import Path

import pytest

from greengold.cli import cmd_run, load_sources_and_ast
from greengold.typecheck import check_program
from .helpers import HAS_CC


def _check(path: Path) -> list[str]:
    program, _, diags = load_sources_and_ast([str(path)])
    if not diags.has_errors():
        check_program(program, diags, str(path))
    return [d.message for d in diags.items if not d.hidden]


def test_qualified_impl_sees_imported_self(tmp_path: Path):
    """`impl shapes.Circle` with bare `self` is `shapes.Circle`, not a name in this file."""
    types = tmp_path / "types"
    types.mkdir()
    (types / "shapes.gg").write_text(
        "public\n"
        "struct Circle:\n"
        "    radius: f64\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "types/shapes.gg"\n\n'
        "impl shapes.Circle:\n"
        "    fn area(self) -> f64:\n"
        "        return self.radius\n"
        "    fn grown(self) -> Self:\n"
        "        return Self{ radius: self.radius }\n\n"
        "fn main():\n"
        "    c = shapes.Circle{ radius: 2.0 }\n"
        "    print(c.area())\n",
        encoding="utf-8",
    )
    assert _check(main) == []


def test_single_file_names_stay_bare(tmp_path: Path):
    main = tmp_path / "main.gg"
    main.write_text(
        "fn add(a: i32, b: i32) -> i32:\n"
        "    return a + b\n\n"
        "fn main():\n"
        "    print(add(2, 3))\n",
        encoding="utf-8",
    )
    assert _check(main) == []


def test_qualified_call_private_name_and_selective_import(tmp_path: Path):
    lib = tmp_path / "mathx.gg"
    lib.write_text(
        "public\n"
        "fn twice(n: i32) -> i32:\n"
        "    return n * 2\n\n"
        "private\n"
        "fn hidden() -> i32:\n"
        "    return 1\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "mathx.gg"\n\n'
        "fn main():\n"
        "    print(mathx.twice(21))\n"
        "    print(mathx.hidden())\n",
        encoding="utf-8",
    )
    msgs = _check(main)
    assert any("private" in m for m in msgs)
    assert not any("twice" in m and "no `" in m for m in msgs)

    picked = tmp_path / "picked.gg"
    picked.write_text(
        'import "mathx.gg" { twice }\n\n'
        "fn main():\n"
        "    print(twice(4))\n",
        encoding="utf-8",
    )
    assert _check(picked) == []


def test_visibility_does_not_cross_files(tmp_path: Path):
    (tmp_path / "a.gg").write_text(
        "public\n"
        "fn open_a() -> i32:\n    return 1\n\n"
        "private\n"
        "fn shut_a() -> i32:\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "b.gg").write_text(
        "fn open_b() -> i32:\n    return 4\n\n"
        "private\n"
        "fn shut_b() -> i32:\n    return 3\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "a.gg"\n'
        'import "b.gg"\n\n'
        "fn main():\n"
        "    print(a.open_a() + b.open_b())\n"
        "    print(a.shut_a())\n"
        "    print(b.shut_b())\n",
        encoding="utf-8",
    )
    msgs = _check(main)
    assert not any("open_a" in m or "open_b" in m for m in msgs)
    assert any("shut_a" in m and "private" in m for m in msgs)
    assert any("shut_b" in m and "private" in m for m in msgs)


def test_import_alias_and_same_private_name(tmp_path: Path):
    (tmp_path / "left.gg").write_text(
        "fn helper() -> i32:\n    return 1\n\npublic\nfn from_left() -> i32:\n    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "right.gg").write_text(
        "fn helper() -> i32:\n    return 2\n\npublic\nfn from_right() -> i32:\n    return helper()\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "left.gg" as left\n'
        'import "right.gg" as right\n\n'
        "fn main():\n"
        "    print(left.from_left() + right.from_right())\n",
        encoding="utf-8",
    )
    assert _check(main) == []


def test_import_name_collision(tmp_path: Path):
    (tmp_path / "a.gg").write_text("public\nfn f() -> i32:\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.gg").write_text("public\nfn g() -> i32:\n    return 2\n", encoding="utf-8")
    main = tmp_path / "main.gg"
    main.write_text(
        'import "a.gg" as util\n'
        'import "b.gg" as util\n\n'
        "fn main():\n"
        "    pass\n",
        encoding="utf-8",
    )
    assert any("already used" in m for m in _check(main))


def test_main_only_in_root(tmp_path: Path):
    (tmp_path / "lib.gg").write_text("fn main():\n    pass\n", encoding="utf-8")
    main = tmp_path / "main.gg"
    main.write_text(
        'import "lib.gg"\n\n'
        "fn main():\n"
        "    pass\n",
        encoding="utf-8",
    )
    assert any("only allowed in the program root" in m for m in _check(main))


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_qualified_call_runs(tmp_path: Path):
    (tmp_path / "mathx.gg").write_text(
        "public\nfn twice(n: i32) -> i32:\n    return n * 2\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "mathx.gg"\n\n'
        "fn main():\n"
        "    print(mathx.twice(21))\n",
        encoding="utf-8",
    )
    assert cmd_run([str(main)]) == 0
