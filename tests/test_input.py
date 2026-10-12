from pathlib import Path
import subprocess
import sys
import pytest
from greengold.cli import compile_to_ir
from greengold.diagnostics import CompileError
from .helpers import HAS_CC


def test_input_typecheck():
    src = (
        "fn main():\n"
        '    s = input()\n'
        '    prompted = input("Name: ")\n'
        '    print(s, prompted)\n'
    )
    compile_to_ir(src)


def test_input_typecheck_errors():
    with pytest.raises(CompileError) as exc:
        compile_to_ir("fn main():\n    x = input(123)\n")
    assert any("str" in d.message for d in exc.value.diagnostics)

    with pytest.raises(CompileError) as exc:
        compile_to_ir('fn main():\n    x = input("a", "b")\n')
    assert any("at most 1" in d.message for d in exc.value.diagnostics)


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_input_e2e_single(tmp_path: Path):
    prog = tmp_path / "prog.gg"
    prog.write_text(
        "fn main():\n"
        "    line = input()\n"
        '    print("Input:", line)\n',
        encoding="utf-8"
    )

    res = subprocess.run(
        [sys.executable, "-m", "greengold", "run", str(prog)],
        input="Hello World\n",
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    assert res.returncode == 0
    assert "Input: Hello World" in res.stdout


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_input_e2e_prompt_and_multiple_inputs(tmp_path: Path):
    prog = tmp_path / "prog.gg"
    prog.write_text(
        "fn main():\n"
        '    first = input("First: ")\n'
        '    second = input("Last: ")\n'
        '    print("Full Name:", first, second)\n',
        encoding="utf-8"
    )

    res = subprocess.run(
        [sys.executable, "-m", "greengold", "run", str(prog)],
        input="Ada\nLovelace\n",
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    assert res.returncode == 0
    assert "First: Last: Full Name: Ada Lovelace" in res.stdout or "Full Name: Ada Lovelace" in res.stdout
    assert "Ada Lovelace" in res.stdout


@pytest.mark.skipif(not HAS_CC, reason="No C compiler found")
def test_input_string_comparison(tmp_path: Path):
    prog = tmp_path / "prog.gg"
    prog.write_text(
        "fn main():\n"
        '    cmd = input()\n'
        '    if cmd == "start":\n'
        '        print("Started")\n'
        '    else:\n'
        '        print("Unknown command")\n',
        encoding="utf-8"
    )

    res1 = subprocess.run(
        [sys.executable, "-m", "greengold", "run", str(prog)],
        input="start\n",
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    assert res1.returncode == 0
    assert "Started" in res1.stdout

    res2 = subprocess.run(
        [sys.executable, "-m", "greengold", "run", str(prog)],
        input="stop\n",
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    assert res2.returncode == 0
    assert "Unknown command" in res2.stdout

