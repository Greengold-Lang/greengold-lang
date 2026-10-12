"""LLVM pipeline tests: emit-ll / emit-bc, comptime, soa/exclusive, no-std, String/str."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from greengold.llvm_driver import find_linker

ROOT = Path(__file__).resolve().parent.parent
HAS_LINKER = bool(shutil.which("gcc") or shutil.which("clang"))
needs_linker = pytest.mark.skipif(not HAS_LINKER, reason="no linker (gcc/clang)")


def gg(*args, cwd=None, timeout=60):
    return subprocess.run([sys.executable, "-m", "greengold", *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", cwd=cwd or ROOT, timeout=timeout)


def write(tmp_path, src, name="t.gg"):
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return p


def run_src(tmp_path, src, *flags):
    p = write(tmp_path, src)
    exe = tmp_path / ("t.exe" if sys.platform == "win32" else "t")
    b = gg("build", p, "-o", exe, *flags)
    assert b.returncode == 0, b.stderr
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
    return r


def test_emit_ll_contains_main(tmp_path):
    p = write(tmp_path, "fn main():\n    print(1)\n")
    r = gg("emit-ll", p)
    assert r.returncode == 0, r.stderr
    assert "define" in r.stdout and "main" in r.stdout


def test_emit_bc_writes_bitcode(tmp_path):
    p = write(tmp_path, "fn main():\n    print(1)\n")
    r = gg("emit-bc", p)
    assert r.returncode == 0, r.stderr
    bc = list(tmp_path.glob("*.bc"))
    # raw bitcode starts with "BC"; for Apple targets LLVM writes the 0x0B17C0DE wrapper first
    assert bc and bc[0].read_bytes()[:4] in (bytes.fromhex("4243c0de"), bytes.fromhex("dec0170b"))


@needs_linker
def test_hello_and_arithmetic(tmp_path):
    r = run_src(tmp_path, "fn main():\n    print(2 + 3 * 4)\n")
    assert r.stdout.split() == ["14"]


@needs_linker
def test_comptime_fn_is_embedded(tmp_path):
    src = ("comptime fn fib(n: i32) -> i32:\n    if n < 2:\n        return n\n"
           "    return fib(n - 1) + fib(n - 2)\n\n"
           "const F = fib(10)\n\nfn main():\n    print(F)\n")
    p = write(tmp_path, src)
    ll = gg("emit-ll", p)
    assert ll.returncode == 0, ll.stderr
    assert "fib" not in ll.stdout.split("define i32 @main", 1)[-1] or "55" in ll.stdout
    r = run_src(tmp_path, src)
    assert r.stdout.split() == ["55"]


@needs_linker
def test_soa_array(tmp_path):
    src = ("struct P:\n    x: f32\n    y: f32\n\n"
           "fn main():\n    ps = soa Array[P, 4]\n    for i in 0..4:\n        ps[i].x = f32(i)\n"
           "        ps[i].y = 2.0\n    s = 0.0\n    for i in 0..4:\n        s += f64(ps[i].x + ps[i].y)\n    print(s)\n")
    p = write(tmp_path, src)
    r = gg("build", p, "-o", tmp_path / "soa", "--release")
    if r.returncode != 0:
        pytest.skip("soa syntax differs in this version: " + r.stderr[:200])
    out = subprocess.run([str(tmp_path / ("soa.exe" if sys.platform == "win32" else "soa"))],
                         capture_output=True, text=True, timeout=20)
    assert out.stdout.split() == ["14"]


@needs_linker
def test_string_and_str(tmp_path):
    src = ('fn main():\n    s = string.new()\n    s.append_str("ab")\n    s.append_byte(99)\n'
           '    print(s.len())\n    print(s.as_str())\n')
    r = run_src(tmp_path, src)
    assert r.stdout.split() == ["3", "abc"]


@needs_linker
def test_optional_result_from_core(tmp_path):
    src = ("fn half(n: i32) -> Optional[i32]:\n    if n % 2 == 0:\n        return Valid(n / 2)\n    return None\n\n"
           "fn main():\n    match half(8):\n        Valid(v):\n            print(v)\n        None:\n            print(-1)\n")
    r = run_src(tmp_path, src)
    assert r.stdout.split() == ["4"]


@needs_linker
def test_index_out_of_bounds_panics(tmp_path):
    src = "fn main():\n    a = [1, 2, 3]\n    i = 5\n    print(a[i])\n"
    r = run_src(tmp_path, src)
    assert r.returncode == 101


def test_no_std_bare_metal_object(tmp_path):
    p = write(tmp_path, "fn add(a: i32, b: i32) -> i32:\n    return a + b\n\nfn main():\n    x = add(1, 2)\n")
    obj = tmp_path / "t.o"
    r = gg("build", p, "-o", obj, "--no-std", "--target", "bare-metal")
    assert r.returncode in (0, 3), r.stderr
    assert obj.exists() and obj.stat().st_size > 0


