"""The two LLVM back ends (llvmlite, an outside clang) and type sizes read from a data layout string."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import llvmlite.ir as ir
import pytest

from greengold import datalayout, llvm_driver, llvm_tools

ROOT = Path(__file__).resolve().parent.parent
TRIPLES = ["x86_64-w64-windows-gnu", "x86_64-unknown-linux-gnu", "aarch64-apple-darwin", "aarch64-unknown-linux-gnu",
           "riscv64-unknown-linux-gnu", "wasm32-unknown-unknown", "thumbv7em-none-eabihf", "i686-unknown-linux-gnu"]


def _types() -> list[ir.Type]:
    i8, i16, i32, i64 = ir.IntType(8), ir.IntType(16), ir.IntType(32), ir.IntType(64)
    ptr = ir.IntType(8).as_pointer()
    f32, f64 = ir.FloatType(), ir.DoubleType()
    base = [ir.IntType(1), i8, i16, i32, i64, ir.IntType(128), ir.IntType(24), ir.IntType(65), f32, f64, ptr]
    out = list(base)
    out += [ir.ArrayType(t, n) for t in (i8, i32, f64, ptr) for n in (0, 1, 3, 12)]
    out += [ir.LiteralStructType([i8, i64]), ir.LiteralStructType([i32, i8]), ir.LiteralStructType([ptr, i64, i64]),
            ir.LiteralStructType([i8, ir.LiteralStructType([i16, f64]), i8]), ir.LiteralStructType([]),
            ir.LiteralStructType([i32, ir.ArrayType(i8, 5)]), ir.LiteralStructType([i8, i64], packed=True),
            ir.LiteralStructType([ir.IntType(128), i8])]
    out += [ir.VectorType(f32, 4), ir.VectorType(f64, 2), ir.VectorType(i32, 8), ir.VectorType(f32, 3),
            ir.VectorType(i8, 16), ir.VectorType(i64, 4)]
    return out


@pytest.mark.skipif(not llvm_driver.has_llvmlite(), reason="llvmlite not installed")
@pytest.mark.parametrize("triple", TRIPLES)
def test_sizes_match_llvm(triple):
    import llvmlite.binding as llvm
    from greengold.codegen_llvm import init_llvm
    os.environ.pop("GG_BACKEND", None)
    init_llvm()
    try:
        td = llvm.Target.from_triple(triple).create_target_machine().target_data
    except RuntimeError:
        pytest.skip(f"llvmlite has no {triple} target")
    layout = str(td)
    for ty in _types():
        want = ty.get_abi_size(td)
        assert datalayout.abi_size(ty, layout) == want, (triple, layout, str(ty))


def test_backend_follows_gg_backend(monkeypatch):
    monkeypatch.setenv("GG_BACKEND", "clang")
    assert llvm_driver.backend() == "clang"
    monkeypatch.setenv("GG_BACKEND", "llvmlite")
    assert llvm_driver.backend() == "llvmlite"


@pytest.mark.skipif(not llvm_driver.has_llvmlite(), reason="llvmlite not installed")
def test_backend_default_prefers_the_newer_llvm(monkeypatch):
    monkeypatch.delenv("GG_BACKEND", raising=False)
    clang23 = (("clang",), 23)
    for mine, outside, want in [(22, clang23, "llvmlite"), (14, clang23, "clang"), (14, None, "llvmlite"),
                                (14, (("clang",), 14), "llvmlite")]:
        monkeypatch.setattr(llvm_driver, "llvmlite_major", lambda m=mine: m)
        monkeypatch.setattr(llvm_tools, "find", lambda o=outside: o)
        assert llvm_driver.backend() == want, (mine, outside)


@pytest.mark.skipif(llvm_tools.find() is None, reason="no clang 15+ found")
def test_outside_llvm_builds_and_runs(tmp_path):
    src = tmp_path / "main.gg"
    src.write_text("""
struct P:
    a: i8
    b: i64

fn main():
    xs = List[P]()
    for i in 0..1000:
        xs.push(P{ a: i8(i % 100), b: i64(i) * 3 })
    total: i64 = 0
    for p in xs:
        total += i64(p.a) + p.b
    words = 0
    for w in "  one two\\tthree ".split_whitespace():
        words += 1
    print(total, words)
""", encoding="utf-8")
    exe = tmp_path / ("main.exe" if sys.platform == "win32" else "main")
    env = dict(os.environ, GG_BACKEND="clang")
    for release in ([], ["--release"]):
        build = subprocess.run([sys.executable, "-m", "greengold", "build", str(src), "-o", str(exe), *release],
                               capture_output=True, text=True, cwd=tmp_path, env=env)
        assert build.returncode == 0, build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        assert run.stdout.split() == ["1548000", "3"], run.stdout + run.stderr


@pytest.mark.skipif(llvm_tools.find() is None, reason="no clang 15+ found")
def test_outside_llvm_reports_invalid_ir():
    with pytest.raises(llvm_tools.ToolError, match="invalid"):
        llvm_tools.object_code("define i32 @f() {\n  ret i64 0\n}\n", "x86_64-unknown-linux-gnu", False)
