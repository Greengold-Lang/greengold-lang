import subprocess
import sys
from pathlib import Path
import pytest

from greengold.lexer import tokenize
from greengold.diagnostics import DiagnosticBag
from greengold.parser import parse
from greengold.typecheck import TypeChecker
from greengold.codegen_llvm import LLVMGen

ROOT = Path(__file__).resolve().parent.parent


def compile_to_ll(src: str, release: bool = False) -> str:
    d = DiagnosticBag()
    toks = tokenize(src, d)
    assert not d.has_errors(), [item.message for item in d.items]
    prog = parse(toks, d)
    assert not d.has_errors(), [item.message for item in d.items]
    tc = TypeChecker(prog, d)
    tc.check()
    assert not tc.diags.has_errors(), [item.message for item in tc.diags.items]
    gen = LLVMGen(prog, release=release)
    return gen.generate()


def run_prog(tmp_path: Path, src: str) -> subprocess.CompletedProcess[str]:
    p = tmp_path / "main.gg"
    p.write_text(src, encoding="utf-8")
    exe = tmp_path / ("t.exe" if sys.platform == "win32" else "t")
    build = subprocess.run([sys.executable, "-m", "greengold", "build", str(p), "-o", str(exe)],
                           capture_output=True, text=True, cwd=ROOT)
    assert build.returncode == 0, build.stderr
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)


def test_require_eliminates_bounds_check_in_dot():
    src = """
fn dot(a: []f32, b: []f32) -> f32:
    require a.len == b.len
    total: f32 = 0.0
    for i in range a.len:
        total = total + a[i] * b[i]
    return total

fn main():
    pass
"""
    ll = compile_to_ll(src)
    # Check that in gg_dot there are NO bounds checks inside the loop body
    func_lines = []
    in_dot = False
    for line in ll.splitlines():
        if 'define internal float @"gg_dot"' in line:
            in_dot = True
        elif in_dot and line.startswith("}"):
            in_dot = False
        elif in_dot:
            func_lines.append(line)
    dot_ir = "\n".join(func_lines)
    
    # Require statement itself generates a check
    assert "require condition failed" in ll
    assert "gg_rt_panic" in dot_ir
    # But inside the loop body, neither a[i] nor b[i] should have bounds checks!
    assert "panic_bounds" not in dot_ir
    assert "index out of bounds" not in dot_ir
    # Check that both a and b are accessed with getelementptr inbounds
    assert dot_ir.count("getelementptr inbounds float, float*") == 2


def test_require_runtime_success(tmp_path: Path):
    src = """
fn dot(a: []f64, b: []f64) -> f64:
    require a.len == b.len
    total: f64 = 0.0
    for i in range a.len:
        total = total + a[i] * b[i]
    return total

fn main():
    a: [3]f64 = [1.0, 2.0, 3.0]
    b: [3]f64 = [4.0, 5.0, 6.0]
    res: f64 = dot(a, b)
    if res == 32.0:
        print("OK: 32")
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode == 0
    assert "OK: 32" in proc.stdout


def test_require_runtime_failure(tmp_path: Path):
    src = """
fn dot(a: []f64, b: []f64) -> f64:
    require a.len == b.len
    return 0.0

fn main():
    a: [2]f64 = [1.0, 2.0]
    b: [3]f64 = [1.0, 2.0, 3.0]
    dot(a, b)
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode != 0
    assert "require condition failed" in proc.stderr


@pytest.mark.parametrize("cond,shown", [
    ("add(2, 3) == 5", "add(2, 3) == 5 (left: 6, right: 5)"),
    ('"ab" == "cd"', '"ab" == "cd" (left: "ab", right: "cd")'),
    ("1.5 < 0.25", "1.5 < 0.25 (left: 1.5, right: 0.25)"),
    ("add(1, 1) != 3", "add(1, 1) != 3 (left: 3, right: 3)"),
    ("add(1, 1) > 9 and true", "require condition failed: add(1, 1) > 9 and true"),
])
def test_require_failure_shows_operands(tmp_path: Path, cond: str, shown: str):
    src = f"fn add(a: i32, b: i32) -> i32:\n    return a + b + 1\n\nfn main():\n    require {cond}\n"
    proc = run_prog(tmp_path, src)
    assert proc.returncode != 0
    assert shown in proc.stderr, proc.stderr
