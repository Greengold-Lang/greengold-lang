"""Bounded integer types and bounds check elimination.
- Bounded int syntax: `int in 0..256`, `i64 in 0..256`
- Out of bounds literal compile error
- Automatic narrowing of `x & mask` and `x % N`
- Bounds check eliminated when indexing fixed array with matching bounded int
- LLVM `!range` metadata emission
- End-to-end execution
"""
import sys
import subprocess
from pathlib import Path

import pytest
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse
from greengold.typecheck import TypeChecker
from greengold.codegen_llvm import generate_llvm

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
    mod = generate_llvm(prog, release=release)
    return str(mod)


def check_diagnostics(src: str) -> list[str]:
    d = DiagnosticBag()
    toks = tokenize(src, d)
    if d.has_errors():
        return [item.message for item in d.items]
    prog = parse(toks, d)
    if d.has_errors():
        return [item.message for item in d.items]
    tc = TypeChecker(prog, d)
    tc.check()
    return [item.message for item in tc.diags.items]


def run_prog(tmp_path: Path, src: str, release: bool = False) -> subprocess.CompletedProcess[str]:
    p = tmp_path / "main.gg"
    p.write_text(src, encoding="utf-8")
    exe = tmp_path / ("t.exe" if sys.platform == "win32" else "t")
    cmd = [sys.executable, "-m", "greengold", "build", str(p), "-o", str(exe)]
    if release:
        cmd.append("--release")
    build = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert build.returncode == 0, build.stderr
    return subprocess.run([str(exe)], capture_output=True, text=True)


def test_bounded_int_typecheck_valid():
    src = """
fn foo():
    x: int in 0..256 = 100
    y: int in 0..256 = x
    z: int in -10..10 = -5

fn main():
    pass
"""
    errs = check_diagnostics(src)
    assert len(errs) == 0, errs


def test_bounded_int_typecheck_out_of_bounds_literal():
    src = """
fn foo():
    x: int in 0..256 = 300

fn main():
    pass
"""
    errs = check_diagnostics(src)
    assert any("out of bounds" in e for e in errs), errs


def test_bounded_int_typecheck_inverted_range():
    src = """
fn foo():
    x: int in 256..0 = 10

fn main():
    pass
"""
    errs = check_diagnostics(src)
    assert any("lower bound must be less than upper bound" in e for e in errs), errs


def test_bounded_int_automatic_narrowing_bitwise_and():
    src = """
fn foo(x: int):
    idx: int in 0..256 = x & 255

fn main():
    pass
"""
    errs = check_diagnostics(src)
    assert len(errs) == 0, errs


def test_unbounded_int_cannot_assign_to_bounded():
    src = """
fn foo(x: int):
    idx: int in 0..256 = x

fn main():
    pass
"""
    errs = check_diagnostics(src)
    assert any("Expected bounded integer" in e for e in errs), errs


def test_bounded_int_eliminates_array_bounds_check():
    src = """
fn lookup(arr: read [256]i32, idx: int in 0..256) -> i32:
    return arr[idx]

fn main():
    pass
"""
    ll = compile_to_ll(src)
    # The lookup function should not contain call to panic_bounds
    assert "@panic_bounds" not in ll
    # It should have getelementptr inbounds
    assert "getelementptr inbounds [256 x i32]" in ll


def test_bitwise_and_eliminates_array_bounds_check():
    src = """
fn lookup_masked(arr: read [256]i32, x: int) -> i32:
    return arr[x & 255]

fn main():
    pass
"""
    ll = compile_to_ll(src)
    assert "@panic_bounds" not in ll
    assert "getelementptr inbounds [256 x i32]" in ll


def test_bounded_int_range_metadata_emitted():
    src = """
fn get_idx(x: int in 0..256) -> int:
    return x

fn main():
    pass
"""
    ll = compile_to_ll(src)
    # Check that !range metadata is emitted for 0..256
    assert "!range" in ll
    assert "i64 0, i64 256" in ll


def test_bounded_int_e2e_execution(tmp_path: Path):
    src = """
fn fill_and_sum() -> i32:
    table: [256]i32 = [0; 256]
    for i in range 256:
        table[i] = i32(i) * 2

    sum: i32 = 0
    for k in range 100:
        idx: int in 0..256 = k & 255
        sum += table[idx]
    return sum

fn main():
    s = fill_and_sum()
    if s == 9900:
        print("STAGE 4 OK")
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode == 0, proc.stderr
    assert "STAGE 4 OK" in proc.stdout


def test_trusted_index_skips_bounds_check():
    checked = """
fn load0(items: [4]i32) -> i32:
    return items[0]

fn main():
    pass
"""
    trusted = """
hot fn load0(items: [4]i32) -> i32:
    unsafe:
        return trust items[0]

fn main():
    pass
"""
    assert "panic_bounds" in compile_to_ll(checked, release=True)
    assert "panic_bounds" not in compile_to_ll(trusted, release=True)


def test_trust_requires_unsafe():
    for head in ("fn", "hot fn"):  # `hot fn` is a performance hint, not a license to skip bounds checks
        src = f"""
{head} load0(items: [4]i32) -> i32:
    return trust items[0]

fn main():
    pass
"""
        msgs = check_diagnostics(src)
        assert any("`unsafe:`" in m for m in msgs), (head, msgs)
