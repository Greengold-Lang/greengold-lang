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


def run_prog(tmp_path: Path, src: str, release: bool = False) -> subprocess.CompletedProcess[str]:
    p = tmp_path / "main.gg"
    p.write_text(src, encoding="utf-8")
    exe = tmp_path / ("t.exe" if sys.platform == "win32" else "t")
    cmd = [sys.executable, "-m", "greengold", "build", str(p), "-o", str(exe)]
    if release:
        cmd.append("--release")
    build = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert build.returncode == 0, build.stderr
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)


def test_default_add_overflow_traps(tmp_path: Path):
    src = """
fn main():
    a: i32 = 2147483647
    b: i32 = a + 1
    print(b)
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode != 0
    assert "integer overflow" in proc.stderr


def test_default_sub_overflow_traps(tmp_path: Path):
    src = """
fn main():
    a: i32 = -2147483648
    b: i32 = a - 1
    print(b)
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode != 0
    assert "integer overflow" in proc.stderr


def test_default_mul_overflow_traps(tmp_path: Path):
    src = """
fn main():
    a: i32 = 1000000
    b: i32 = a * 1000000
    print(b)
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode != 0
    assert "integer overflow" in proc.stderr


def test_release_mode_overflow_traps(tmp_path: Path):
    src = """
fn main():
    a: i32 = 2147483647
    b: i32 = a + 1
    print(b)
"""
    proc = run_prog(tmp_path, src, release=True)
    assert proc.returncode != 0
    assert "integer overflow" in proc.stderr


def test_wrapping_block(tmp_path: Path):
    src = """
fn main():
    a: i32 = 2147483647
    res: i32 = 0
    wrapping:
        res = a + 1
    if res == -2147483648:
        print("OK: WRAP")
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode == 0
    assert "OK: WRAP" in proc.stdout


def test_function_level_overflow_wrap(tmp_path: Path):
    src = """
fn my_hash(x: u64) -> u64:
    overflow: wrap
    return x * 1000000007 + 123456789

fn main():
    h: u64 = my_hash(18446744073709551615)
    print("HASH OK")
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode == 0
    assert "HASH OK" in proc.stdout


def test_infix_wrapping_ops(tmp_path: Path):
    src = """
fn main():
    a: i32 = 2147483647
    b = a wrapping_add 1
    c = b wrapping_sub 1
    d: i32 = 65536
    e = d wrapping_mul 65536
    if b == -2147483648 and c == 2147483647 and e == 0:
        print("INFIX WRAP OK")
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode == 0
    assert "INFIX WRAP OK" in proc.stdout


def test_infix_saturating_ops(tmp_path: Path):
    src = """
fn main():
    a: i32 = 2147483647
    b = a saturating_add 5
    c: i32 = -2147483647
    d = c saturating_sub 10
    if b == 2147483647 and d == -2147483648:
        print("SATURATING OK")
"""
    proc = run_prog(tmp_path, src)
    assert proc.returncode == 0
    assert "SATURATING OK" in proc.stdout


def test_critical_security_no_nsw_nuw_on_wrapping():
    """CRITICAL SECURITY RULE:
    LLVM `nsw` and `nuw` flags MUST NEVER be emitted on wrapping operations.
    Otherwise LLVM generates poison values, causing silent miscompilations.
    """
    code_fn = """
fn calc(a: i32, b: i32) -> i32:
    overflow: wrap
    return (a + b) * (a - b)

fn main():
    pass
"""
    ll_fn = compile_to_ll(code_fn)
    assert "nsw" not in ll_fn
    assert "nuw" not in ll_fn

    code_blk = """
fn calc2(a: i32, b: i32) -> i32:
    res: i32 = 0
    wrapping:
        res = a + b
    return res

fn main():
    pass
"""
    ll_blk = compile_to_ll(code_blk)
    assert "nsw" not in ll_blk
    assert "nuw" not in ll_blk

    code_infix = """
fn calc3(a: i32, b: i32) -> i32:
    return a wrapping_add b

fn main():
    pass
"""
    ll_infix = compile_to_ll(code_infix)
    assert "nsw" not in ll_infix
    assert "nuw" not in ll_infix


def test_counter_in_constant_loop_has_no_check(tmp_path: Path):
    # `n` and `t` cannot pass N * step inside the loop, so their additions need no check (counters.py).
    src = """
const N: usize = 1000

fn main():
    xs = List[i64]()
    for i in 0..N:
        xs.push(i64(i * 7 % 3))
    n: i64 = 0
    t: u32 = 5
    for i in 0..N:
        if xs[i] != 0:
            n += 1
            t += 2
    print(n, t)
"""
    ll = compile_to_ll(src)
    assert "sadd.with.overflow.i64" not in ll and "uadd.with.overflow.i32" not in ll
    r = run_prog(tmp_path, src, release=True)
    assert r.stdout.split() == ["666", "1337"], r.stdout + r.stderr


def test_counter_that_can_overflow_keeps_check(tmp_path: Path):
    src = """
fn main():
    big: i8 = 0
    for i in 0..300:
        big += 1
    print(big)
"""
    r = run_prog(tmp_path, src, release=True)
    assert r.returncode != 0 and "integer overflow" in r.stderr, r.stdout + r.stderr


def test_counter_used_otherwise_keeps_check():
    # Passed as `lend`, or started from a value that is not a literal: the analysis does not apply.
    src = """
fn bump(x: lend i64):
    x += 1

fn main():
    a: i64 = 0
    for i in 0..10:
        bump(a)
        a += 1
    b = a
    for i in 0..10:
        b += 1
    print(a, b)
"""
    ll = compile_to_ll(src)
    assert ll.count("sadd.with.overflow.i64") >= 3
