"""`-g`: DWARF debug information (functions, lines, locals)."""
import shutil
import subprocess

import pytest

from greengold.cli import main

SRC = """struct Point:
    x: i32
    y: f64

fn area(p: Point) -> f64:
    total = p.y * 2.0
    return total

fn main():
    p = Point{ x: 3, y: 1.5 }
    print(area(p))
"""


def test_debug_ir_has_functions_lines_and_locals(tmp_path):
    src = tmp_path / "dbg.gg"
    src.write_text(SRC, encoding="utf-8")
    out = tmp_path / "dbg.ll"
    try:
        assert main(["emit-ll", "-g", str(src), "-o", str(out)]) == 0
    finally:
        main(["emit-ll", str(src), "-o", str(tmp_path / "plain.ll")])  # leave the flag off for other tests
    text = out.read_text(encoding="utf-8")
    assert 'DISubprogram(' in text and 'name: "area"' in text
    assert 'DILocalVariable(' in text and 'name: "total"' in text
    assert "!dbg" in text
    assert "DISubprogram" not in (tmp_path / "plain.ll").read_text(encoding="utf-8")


def _skip_if_gdb_cannot_load(res):
    """Some gdb builds (Cygwin/MSYS ones on CI) cannot open a native Windows .exe or path."""
    err = res.stderr
    if "No executable specified" in err or "not in executable format" in err or "Excess command line" in err:
        pytest.skip(f"this gdb cannot load the program here: {err.strip()[:120]}")


@pytest.mark.skipif(shutil.which("gdb") is None, reason="gdb is not installed")
def test_gdb_stops_on_a_greengold_line(tmp_path):
    src = tmp_path / "dbg.gg"
    src.write_text(SRC, encoding="utf-8")
    exe = tmp_path / "dbg.exe"
    try:
        assert main(["build", "-g", str(src), "-o", str(exe)]) == 0
    finally:
        main(["emit-ll", str(src), "-o", str(tmp_path / "plain.ll")])
    res = subprocess.run(["gdb", "-batch", "-ex", "break dbg.gg:7", "-ex", "run", "-ex", "print p", "-ex", "print total",
                          str(exe)], capture_output=True, text=True, timeout=60)
    _skip_if_gdb_cannot_load(res)
    assert "dbg.gg:7" in res.stdout
    assert "{x = 3, y = 1.5}" in res.stdout
    assert "= 3" in res.stdout


VALUES = """struct P:
    name: string
    xs: List[i32]

enum Shape:
    Circle(f64)
    Rect(i32, i32)
    Empty

fn main():
    s = string.from("hello")
    xs = List[i32]()
    xs.push(1)
    xs.push(2)
    p = P{ name: string.from("pt"), xs: List[i32]() }
    o: Optional[i32] = Valid(7)
    n: Optional[i32] = None
    sh = Shape.Rect(2, 3)
    t = "view"
    names = [string.from("x"), string.from("y")]
    print(s, xs, p.xs, o, n, sh, t, names)
"""


def _build_values(tmp_path):
    src = tmp_path / "vals.gg"
    src.write_text(VALUES, encoding="utf-8")
    exe = tmp_path / "vals.exe"
    try:
        assert main(["build", "-g", str(src), "-o", str(exe)]) == 0
    finally:
        main(["emit-ll", str(src), "-o", str(tmp_path / "plain.ll")])
    return exe


def test_debug_info_describes_strings_lists_and_enums(tmp_path):
    src = tmp_path / "vals.gg"
    src.write_text(VALUES, encoding="utf-8")
    out = tmp_path / "vals.ll"
    try:
        assert main(["emit-ll", "-g", str(src), "-o", str(out)]) == 0
    finally:
        main(["emit-ll", str(src), "-o", str(tmp_path / "plain.ll")])
    text = out.read_text(encoding="utf-8")
    assert 'name: "List[i32]"' in text and 'name: "cap"' in text
    assert 'name: "string"' in text and 'name: "bytes"' in text
    assert 'DIEnumerator(name: "Rect"' in text and "DW_TAG_union_type" in text
    assert 'name: "names"' in text


@pytest.mark.skipif(shutil.which("gdb") is None, reason="gdb is not installed")
def test_gdb_printers_show_values(tmp_path):
    from greengold.cli import debug_scripts
    exe = _build_values(tmp_path)
    cmds = ["-ex", f"source {debug_scripts()['gdb'].as_posix()}", "-ex", "break vals.gg:21", "-ex", "run"]
    for v in ("s", "xs", "p", "o", "n", "sh", "t", "names"):
        cmds += ["-ex", f"print {v}"]
    res = subprocess.run(["gdb", "-batch", *cmds, str(exe)], capture_output=True, text=True, timeout=60)
    _skip_if_gdb_cannot_load(res)
    got = [ln.split(" = ", 1)[1] for ln in res.stdout.splitlines() if ln.startswith("$")]
    assert got == ['"hello"', "List[i32] (len 2) = {1, 2}", '{name = "pt", xs = List[i32] (len 0)}', "Valid(7)",
                   "None", "Rect(2, 3)", '"view"', '{"x", "y"}'], res.stdout + res.stderr


@pytest.mark.skipif(shutil.which("lldb") is None, reason="lldb is not installed")
def test_lldb_formatters_show_values(tmp_path):
    from greengold.cli import debug_scripts
    exe = _build_values(tmp_path)
    res = subprocess.run(["lldb", "-b", "-o", f"command script import {debug_scripts()['lldb'].as_posix()}",
                          "-o", "b vals.gg:21", "-o", "run", "-o", "frame variable s o n sh t names", str(exe)],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout
    if "target create" not in out or "launch failed" in out or "not permitted" in out:  # lldb did not run
        pytest.skip("lldb could not run the program here")
    for line in ['(string) s = "hello"', "(Optional[i32]) o = Valid(7)", "(Optional[i32]) n = None",
                 "(Shape) sh = Rect(2, 3)", '(str) t = "view"', '(string[2]) names = ([0] = "x", [1] = "y")']:
        assert line in out, out
