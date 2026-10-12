"""FFI tests: C/Rust library linking, raw pointers, `unsafe`, variadic extern, `extern struct`, bindgen."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from greengold.cli import compile_to_ir
from greengold.diagnostics import CompileError
from tests.helpers import EXAMPLES_DIR

ROOT = Path(__file__).resolve().parent.parent
GCC = shutil.which("gcc")
RUSTC = shutil.which("rustc")
EXE = ".exe" if sys.platform == "win32" else ""

needs_gcc = pytest.mark.skipif(GCC is None, reason="gcc not found")
needs_rustc = pytest.mark.skipif(RUSTC is None or GCC is None, reason="rustc/gcc not found")

C_LIB = r"""
#include <stdlib.h>
#include <string.h>
typedef struct Vec2 { double x; double y; } Vec2;
typedef struct Node { int value; struct Node *next; } Node;
int my_add(int a, int b) { return a + b; }
long long my_sum(const int *d, size_t n) { long long s = 0; for (size_t i = 0; i < n; i++) s += d[i]; return s; }
void my_double_all(int *d, size_t n) { for (size_t i = 0; i < n; i++) d[i] *= 2; }
void vec2_scale(Vec2 *v, double k) { v->x *= k; v->y *= k; }
const char *my_greeting(void) { return "hello"; }
int *my_alloc_ints(size_t n) { int *p = (int *)malloc(n * sizeof(int)); for (size_t i = 0; i < n; i++) p[i] = (int)(i * i); return p; }
void my_free(void *p) { free(p); }
Node *node_new(int v, Node *next) { Node *n = (Node *)malloc(sizeof(Node)); n->value = v; n->next = next; return n; }
"""

GG_MAIN = """
extern struct Vec2:
    x: f64
    y: f64

extern struct Node:
    value: i32
    next: *mut Node

extern fn my_add(a: i32, b: i32) -> i32
extern fn my_sum(data: *i32, n: usize) -> i64
extern fn my_double_all(data: *mut i32, n: usize)
extern fn vec2_scale(v: lend Vec2, k: f64)
extern fn my_greeting() -> *u8
extern fn my_alloc_ints(n: usize) -> *mut i32
extern fn my_free(p: *void)
extern fn node_new(v: i32, next: *mut Node) -> *mut Node

fn main():
    print(my_add(2, 3))
    nums = [1, 2, 3, 4]
    unsafe:
        print(my_sum(addr(nums), 4))
        my_double_all(addr_mut(nums), 4)
    print(nums[3])
    v = Vec2{ x: 1.5, y: 2.0 }
    vec2_scale(v, 2.0)
    print(v.x, v.y)
    unsafe:
        print(cstr_to_string(my_greeting()))
        sq = my_alloc_ints(5)
        print(sq[4], ptr_offset(sq, 2)[0])
        sq[1] = 77
        print(sq[1])
        my_free(ptr_cast[*void](sq))
        a = node_new(1, null)
        b = node_new(2, a)
        print(b[0].value, b[0].next[0].value, a[0].next == null, b[0].next == null)
        my_free(ptr_cast[*void](a))
        my_free(ptr_cast[*void](b))
"""

GG_EXPECTED = ["5", "10", "8", "3 4", "hello", "16 4", "77", "2 1 true false"]


def _gg(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "greengold", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=_env())


def _env():
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (";" if sys.platform == "win32" else ":") + env.get("PYTHONPATH", "")
    return env


@pytest.fixture(scope="module")
def clib(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("clib")
    (d / "mylib.c").write_text(C_LIB, encoding="utf-8")
    subprocess.run([GCC, "-c", "mylib.c", "-o", "mylib.o"], cwd=d, check=True)
    subprocess.run(["ar", "rcs", "libmylib.a", "mylib.o"], cwd=d, check=True)
    (d / "main.gg").write_text(GG_MAIN, encoding="utf-8")
    return d


# -- linker flags ----------------------------------------------------------------

@needs_gcc
@pytest.mark.parametrize("backend", [[]])
def test_link_path_and_lib(clib: Path, backend: list[str]):
    res = _gg(["run", "main.gg", "-L", str(clib), "--link", "mylib", *backend], clib)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split("\n")[:len(GG_EXPECTED)] == GG_EXPECTED


@needs_gcc
@pytest.mark.parametrize("backend", [[]])
def test_link_file(clib: Path, backend: list[str]):
    res = _gg(["run", "main.gg", "--link-file", str(clib / "mylib.o"), *backend], clib)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split("\n")[:len(GG_EXPECTED)] == GG_EXPECTED


@needs_gcc
def test_gg_link_args_env(clib: Path):
    import os
    env = _env()
    env["GG_LINK_ARGS"] = str(clib / "mylib.o")
    res = subprocess.run([sys.executable, "-m", "greengold", "run", "main.gg"], cwd=clib, capture_output=True,
                         text=True, encoding="utf-8", env=env, timeout=120)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split("\n")[0] == "5"


def test_link_args_helper():
    from greengold.llvm_driver import link_args
    assert link_args(["m", "-L/x", "a/b.a", "c.o"]) == ["-lm", "-L/x", "a/b.a", "c.o"]


# -- examples -----------------------------------------------------------------------------

@pytest.mark.parametrize("backend", [[]])
def test_pointers_example(backend: list[str]):
    res = _gg(["run", str(EXAMPLES_DIR / "ffi" / "pointers.gg"), *backend], ROOT)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split("\n")[:5] == [
        "total: 100", "first: 10 -1", "nums[2] = 99", "nums[3] = 40", "round trip: 20 true"]


@needs_gcc
@pytest.mark.parametrize("backend", [[]])
def test_c_example(tmp_path: Path, backend: list[str]):
    src = EXAMPLES_DIR / "ffi" / "c"
    shutil.copy(src / "mylib.c", tmp_path / "mylib.c")
    shutil.copy(src / "main.gg", tmp_path / "main.gg")
    subprocess.run([GCC, "-c", "mylib.c", "-o", "mylib.o"], cwd=tmp_path, check=True)
    subprocess.run(["ar", "rcs", "libmylib.a", "mylib.o"], cwd=tmp_path, check=True)
    res = _gg(["run", "main.gg", "-L", ".", "--link", "mylib", *backend], tmp_path)
    assert res.returncode == 0, res.stderr
    assert "Hello from C!" in res.stdout
    assert "sq[0] = 99" in res.stdout



# -- variadic -----------------------------------------------------------------------

VARIADIC = """
extern "stdio.h" fn snprintf(buf: *mut u8, n: usize, fmt: *u8, ...) -> i32

fn main():
    buf: [64]u8 = [0; 64]
    unsafe:
        n = snprintf(addr_mut(buf), 64, string_to_cstr("%d|%s|%.1f|%c"), 42, "hi", 2.5, 'x')
        print(n, cstr_to_string(addr(buf)))
"""


@needs_gcc
@pytest.mark.parametrize("backend", [[]])
def test_variadic_snprintf(tmp_path: Path, backend: list[str]):
    (tmp_path / "v.gg").write_text(VARIADIC, encoding="utf-8")
    res = _gg(["run", "v.gg", *backend], tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "11 42|hi|2.5|x"


# -- Rust staticlib ---------------------------------------------------------------------

RUST_LIB = """
#[no_mangle]
pub extern "C" fn rs_add(a: i32, b: i32) -> i32 { a + b }
#[no_mangle]
pub unsafe extern "C" fn rs_fill(p: *mut u8, n: usize) { for i in 0..n { *p.add(i) = (i as u8) * 3; } }
"""

RUST_GG = """
extern fn rs_add(a: i32, b: i32) -> i32
extern fn rs_fill(p: *mut u8, n: usize)

fn main():
    print(rs_add(40, 2))
    buf: [4]u8 = [0; 4]
    unsafe:
        rs_fill(addr_mut(buf), 4)
    print(buf[0], buf[1], buf[2], buf[3])
"""


@needs_rustc
def test_rust_staticlib(tmp_path: Path):
    (tmp_path / "lib.rs").write_text(RUST_LIB, encoding="utf-8")
    target = "x86_64-pc-windows-gnu" if sys.platform == "win32" else None
    cmd = [RUSTC, "--edition", "2021", "--crate-type", "staticlib", "-O", "-C", "panic=abort", "-o", "librs.a", "lib.rs"]
    if target:
        cmd += ["--target", target]
    res = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"rustc staticlib could not be compiled (target may not be installed): {res.stderr[-200:]}")
    (tmp_path / "main.gg").write_text(RUST_GG, encoding="utf-8")
    extra = ["--link", "ws2_32", "--link", "userenv", "--link", "ntdll", "--link", "bcrypt"] \
        if sys.platform == "win32" else ["--link", "dl", "--link", "pthread", "--link", "m"] + ([] if sys.platform == "darwin" else ["--link", "gcc_s"])
    out = _gg(["run", "main.gg", "--link-file", "librs.a", *extra], tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split("\n")[:2] == ["42", "0 3 6 9"]


# -- compile-time checks -------------------------------------------------------------------

def must_fail(src: str, text: str):
    with pytest.raises(CompileError) as exc_info:
        compile_to_ir(src)
    msgs = [d.message for d in exc_info.value.diagnostics]
    assert any(text in m for m in msgs), f"Expected `{text}` not in error messages: {msgs}"


def test_addr_requires_unsafe():
    must_fail("""
fn main():
    x = 5
    r = addr(x)
""", "unsafe")


def test_unsafe_block_allows_addr():
    out = compile_to_ir("""
fn main():
    x = 5
    unsafe:
        r = addr(x)
        print(r[0])
""")
    assert "@\"gg_main\"" in out


def test_pointer_index_outside_unsafe():
    must_fail("""
fn f(p: *i32) -> i32:
    return p[0]

fn main():
    print(1)
""", "unsafe")


def test_extern_pointer_call_requires_unsafe():
    must_fail("""
extern fn get() -> *mut i32

fn main():
    p = get()
""", "unsafe")


def test_write_through_const_pointer():
    must_fail("""
fn f(p: *i32):
    unsafe:
        p[0] = 1

fn main():
    print(1)
""", "read-only pointer")


def test_null_needs_type():
    must_fail("""
fn main():
    p = null
""", "null")


def test_void_pointer_not_dereferenceable():
    must_fail("""
fn f(p: *void) -> i32:
    unsafe:
        return p[0]

fn main():
    print(1)
""", "cannot be dereferenced")


def test_pointer_to_string_rejected():
    must_fail("""
fn f(p: *string):
    pass

fn main():
    print(1)
""", "invalid")


def test_extern_struct_field_must_be_c_compatible():
    must_fail("""
extern struct Bad:
    name: string

fn main():
    print(1)
""", "C-compatible")


def test_extern_union_by_value_rejected():
    must_fail("""
union P:
    x: f64
    n: u64

extern fn f(p: P)

fn main():
    print(1)
""", "cannot be passed to C by value")


def test_extern_struct_with_heap_field_return_rejected():
    must_fail("""
struct P:
    xs: List[i32]

extern fn f() -> P

fn main():
    print(1)
""", "cannot return")


def test_pointer_builtins_names_reserved():
    must_fail("""
fn addr(x: i32) -> i32:
    return x

fn main():
    print(1)
""", "reserved")


def test_generic_function_with_pointer_param():
    src = """
extern fn my_free(p: *void)

fn first[T](p: *T) -> T:
    unsafe:
        return p[0]

fn main():
    x = 7
    unsafe:
        print(first[i32](addr(x)))
"""
    from greengold.cli import compile_to_ir as c
    assert "first" in c(src)


def test_owner_bytes_through_function_pointer():
    # `addr` of a heap owner is a `*u8`; an indirect call must get it as one (it crashed the code generator).
    src = """
fn first_byte(p: *u8) -> u8:
    unsafe:
        return p[0]

fn main():
    xs = List[i32]()
    xs.push(1)
    f: fn(*u8) -> u8 = first_byte
    unsafe:
        print(f(addr(xs)) == first_byte(addr(xs)))
"""
    assert "first_byte" in compile_to_ir(src)


# -- bindgen ---------------------------------------------------------------------------------

HEADER = """
#ifndef MYLIB_H
#define MYLIB_H
#include <stddef.h>
/* comment */
typedef struct Vec2 { double x; double y; } Vec2;
typedef struct Node Node;
struct Node { int value; Node *next; };
typedef unsigned int u32_t;
int my_add(int a, int b);                      // line comment
long long my_sum(const int *data, size_t n);
void my_double_all(int *data, size_t n);
void vec2_scale(Vec2 *v, double k);
const char *my_greeting(void);
void *my_alloc(size_t n);
void my_free(void *p);
int printf(const char *fmt, ...);
unsigned char my_byte(unsigned char c);
#endif
"""


def test_bindgen_output_compiles():
    from greengold.bindgen import bindgen

    out = bindgen(HEADER, header_name="mylib.h")
    assert "extern struct Vec2:" in out
    assert "    x: f64" in out
    assert "extern struct Node:" in out
    assert "    next: *mut Node" in out
    assert 'extern "mylib.h" fn my_add(a: i32, b: i32) -> i32' in out
    assert 'extern "mylib.h" fn my_sum(data: *i32, n: usize) -> i64' in out
    assert 'extern "mylib.h" fn my_double_all(data: *mut i32, n: usize)' in out
    assert 'extern "mylib.h" fn vec2_scale(v: *mut Vec2, k: f64)' in out
    assert 'extern "mylib.h" fn my_greeting() -> *u8' in out
    assert 'extern "mylib.h" fn my_alloc(n: usize) -> *mut void' in out
    assert 'extern "mylib.h" fn my_free(p: *mut void)' in out
    assert 'extern "mylib.h" fn printf(fmt: *u8, ...) -> i32' in out
    assert 'extern "mylib.h" fn my_byte(c: u8) -> u8' in out
    # generated source must parse and pass typecheck
    compile_to_ir(out + "\nfn main():\n    print(my_add(1, 2))\n")


def test_bindgen_without_header_name_and_consts_and_enums():
    from greengold.bindgen import bindgen

    out = bindgen("""
#define MAX_ITEMS 16
#define MASK 0xFF
#define SQUARE(x) ((x)*(x))
enum Color { RED, GREEN = 5, BLUE };
typedef enum { LOW = 1, HIGH } Level;
extern "C" {
int set_level(Level l);
void use_cb(void (*cb)(int));
int fill(int out[], size_t n);
}
typedef struct { int a; } Anon;
union U { int i; float f; };
""")
    assert "const MAX_ITEMS: i32 = 16" in out
    assert "const MASK: i32 = 255" in out
    assert "const GREEN: i32 = 5" in out and "const BLUE: i32 = 6" in out
    assert "const HIGH: i32 = 2" in out
    assert "extern fn set_level(l: i32) -> i32" in out
    assert "extern fn fill(out_: *mut i32, n: usize) -> i32" in out or "extern fn fill(out: *mut i32, n: usize) -> i32" in out
    assert "extern fn use_cb(cb: fn(i32))" in out  # a function pointer parameter
    assert "union U:" in out and "enum Color:" in out
    assert 'extern "' not in out
    compile_to_ir(out + "\nfn main():\n    print(MAX_ITEMS)\n")


@needs_gcc
def test_bindgen_cli_end_to_end(clib: Path):
    (clib / "mylib.h").write_text(HEADER.replace("void *my_alloc(size_t n);\n", ""), encoding="utf-8")
    res = _gg(["bindgen", "mylib.h", "-o", "bound.gg"], clib)
    assert res.returncode == 0, res.stderr
    assert (clib / "bound.gg").exists()
    text = (clib / "bound.gg").read_text(encoding="utf-8")
    assert "extern fn my_add" in text or 'extern "mylib.h" fn my_add' in text

