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


def test_slice_parameter_is_ssa_no_alloca():
    src = """
fn inspect_slice(s: []f32) -> f32:
    return s[0]

fn main():
    pass
"""
    ll = compile_to_ll(src)
    # The slice parameter itself should NOT have an alloca (e.g. %s = alloca {float*, i64} is eliminated)
    assert 'alloca {float*, i64}' not in ll
    # Instead, extracted SSA values are used directly
    assert 'extractvalue {float*, i64} %"s", 0' in ll
    assert 'extractvalue {float*, i64} %"s", 1' in ll


def test_loop_bounds_check_eliminated_range_syntax():
    src = """
fn sum(items: []f32) -> f32:
    total: f32 = 0.0
    for i in range items.len:
        total = total + items[i]
    return total

fn main():
    pass
"""
    ll = compile_to_ll(src)
    # Inside gg_sum, there should be NO bounds check and NO panic bounds call
    func_lines = []
    in_sum = False
    for line in ll.splitlines():
        if 'define internal float @"gg_sum"' in line:
            in_sum = True
        elif in_sum and line.startswith("}"):
            in_sum = False
        elif in_sum:
            func_lines.append(line)
    sum_ir = "\n".join(func_lines)
    assert "panic_bounds" not in sum_ir
    assert "icmp uge" not in sum_ir
    assert "getelementptr inbounds float, float*" in sum_ir


def test_loop_bounds_check_eliminated_standard_range():
    src = """
fn sum2(items: []f32) -> f32:
    total: f32 = 0.0
    for i in 0..items.len:
        total = total + items[i]
    return total

fn main():
    pass
"""
    ll = compile_to_ll(src)
    func_lines = []
    in_sum = False
    for line in ll.splitlines():
        if 'define internal float @"gg_sum2"' in line:
            in_sum = True
        elif in_sum and line.startswith("}"):
            in_sum = False
        elif in_sum:
            func_lines.append(line)
    sum_ir = "\n".join(func_lines)
    assert "panic_bounds" not in sum_ir
    assert "icmp uge" not in sum_ir
    assert "getelementptr inbounds float, float*" in sum_ir


def test_for_x_in_items_no_bounds_check():
    src = """
fn sum_for_in(items: []f32) -> f32:
    total: f32 = 0.0
    for x in items:
        total = total + x
    return total

fn main():
    pass
"""
    ll = compile_to_ll(src)
    func_lines = []
    in_sum = False
    for line in ll.splitlines():
        if 'define internal float @"gg_sum_for_in"' in line:
            in_sum = True
        elif in_sum and line.startswith("}"):
            in_sum = False
        elif in_sum:
            func_lines.append(line)
    sum_ir = "\n".join(func_lines)
    assert "panic_bounds" not in sum_ir
    assert "icmp uge" not in sum_ir


def test_unproven_index_has_cold_noreturn_and_prof_weights():
    src = """
fn get_item(items: []f32, idx: i64) -> f32:
    return items[idx]

fn main():
    pass
"""
    ll = compile_to_ll(src)
    # Bounds check should be present
    assert "icmp uge" in ll
    assert "gg_rt_panic_bounds" in ll
    # Should branch with !prof metadata
    assert "!prof" in ll
    assert '!"branch_weights"' in ll
    # Panic call should have noreturn
    assert 'call void @"gg_rt_panic_bounds"' in ll
    assert "noreturn" in ll
    # Following access uses inbounds
    assert "getelementptr inbounds float" in ll


def test_list_len_has_range_metadata():
    src = """
fn test_len(xs: read List[i32]) -> usize:
    return xs.len

fn main():
    pass
"""
    ll = compile_to_ll(src)
    assert "!range" in ll
    assert "9223372036854775807" in ll


def test_e2e_execution(tmp_path: Path):
    src = """
fn sum(items: []f64) -> f64:
    total: f64 = 0.0
    for i in range items.len:
        total = total + items[i]
    return total

fn main():
    arr = [1.0, 2.5, 3.5]
    res = sum(arr)
    print(res)
"""
    res = run_prog(tmp_path, src)
    assert res.returncode == 0
    assert "7.0" in res.stdout or "7" in res.stdout
