"""Structs passed to C by value and returned by value (the platform's C calling convention, cabi.py)."""
import pytest

from greengold import cabi
from greengold.cli import compile_to_ir
from tests.helpers import HAS_CC, run_built

C_SIDE = r"""
#include <stdint.h>
typedef struct { int32_t a; int32_t b; } Small;
typedef struct { double x; double y; } Pt;
typedef struct { uint8_t v; } Tiny;
typedef struct { int32_t a, b, c; } Three;
typedef struct { float x, y, z; } V3;
typedef struct { Pt min; Pt max; int32_t tag; } Box2;

int32_t small_sum(Small s) { return s.a + s.b; }
double pt_len2(Pt p) { return p.x * p.x + p.y * p.y; }
int32_t tiny_val(Tiny t, int32_t k) { return t.v * k; }
int32_t three_sum(Three t) { t.a = 99; return t.a + t.b + t.c; }
float v3_dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
double box_area(Box2 b) { return (b.max.x - b.min.x) * (b.max.y - b.min.y) + b.tag; }

Small make_small(int32_t a) { Small s = { a, a * 2 }; return s; }
Pt make_pt(double x) { Pt p = { x, x + 1 }; return p; }
V3 make_v3(float k) { V3 v = { k, 2 * k, 3 * k }; return v; }
Box2 make_box(double w) { Box2 b = { { 0, 0 }, { w, w }, 7 }; return b; }
Tiny make_tiny(void) { Tiny t = { 42 }; return t; }
"""

GG_SIDE = """\
extern struct Small:
    a: i32
    b: i32

extern struct Pt:
    x: f64
    y: f64

extern struct Tiny:
    v: u8

extern struct Three:
    a: i32
    b: i32
    c: i32

extern struct V3:
    x: f32
    y: f32
    z: f32

extern struct Box2:
    min: Pt
    max: Pt
    tag: i32

extern "x.h" fn small_sum(s: Small) -> i32
extern "x.h" fn pt_len2(p: Pt) -> f64
extern "x.h" fn tiny_val(t: Tiny, k: i32) -> i32
extern "x.h" fn three_sum(t: Three) -> i32
extern "x.h" fn v3_dot(a: V3, b: V3) -> f32
extern "x.h" fn box_area(b: Box2) -> f64
extern "x.h" fn make_small(a: i32) -> Small
extern "x.h" fn make_pt(x: f64) -> Pt
extern "x.h" fn make_v3(k: f32) -> V3
extern "x.h" fn make_box(w: f64) -> Box2
extern "x.h" fn make_tiny() -> Tiny

fn main():
    t = Three{ a: 1, b: 2, c: 3 }
    unsafe:
        print(small_sum(Small{ a: 3, b: 4 }), pt_len2(Pt{ x: 3.0, y: 4.0 }), tiny_val(Tiny{ v: 5 }, 3))
        print(three_sum(t), t.a, v3_dot(V3{ x: 1.0, y: 2.0, z: 3.0 }, V3{ x: 4.0, y: 5.0, z: 6.0 }))
        print(box_area(Box2{ min: Pt{ x: 1.0, y: 1.0 }, max: Pt{ x: 3.0, y: 4.0 }, tag: 1 }))
        s = make_small(5)
        p = make_pt(1.5)
        v = make_v3(2.0)
        b = make_box(2.0)
        print(s.a, s.b, p.x, p.y, v.x, v.y, v.z, b.max.x, b.tag, make_tiny().v)
"""


@pytest.mark.skipif(not HAS_CC, reason="needs a C compiler")
def test_structs_cross_to_c_by_value():
    r = run_built(GG_SIDE, extra_c=C_SIDE)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "7 25 15",
        "104 1 32",
        "7",
        "5 10 1.5 2.5 2 4 6 2 7 42",
    ]


@pytest.mark.parametrize("triple, sig", [
    ("x86_64-pc-windows-msvc", 'declare i32 @"small_sum"(i64'),
    ("x86_64-unknown-linux-gnu", 'declare i32 @"small_sum"(i64'),
    ("aarch64-unknown-linux-gnu", 'declare i32 @"small_sum"(i64'),
])
def test_small_struct_lowering(triple, sig):
    ir_text = compile_to_ir(GG_SIDE, target=triple)
    assert sig in ir_text


def test_classification_matches_clang():
    """What clang emits for these C structs on each target."""
    pt = [cabi.Leaf(0, 8, "double"), cabi.Leaf(8, 8, "double")]
    v3 = [cabi.Leaf(0, 4, "float"), cabi.Leaf(4, 4, "float"), cabi.Leaf(8, 4, "float")]
    mixed = [cabi.Leaf(0, 4, "int"), cabi.Leaf(4, 4, "float")]
    sysv = "x86_64-unknown-linux-gnu"
    assert [str(t) for t in cabi.plan_param(pt, 16, 8, sysv).parts] == ["double", "double"]
    assert [str(t) for t in cabi.plan_param(v3, 12, 4, sysv).parts] == ["<2 x float>", "float"]
    assert [str(t) for t in cabi.plan_param(mixed, 8, 4, sysv).parts] == ["i64"]
    assert cabi.plan_param(pt + pt, 32, 8, sysv).how == "byval"
    assert cabi.plan_result(pt + pt, 32, 8, sysv).how == "sret"
    win = "x86_64-pc-windows-msvc"
    assert cabi.plan_param(pt, 16, 8, win).how == "indirect"
    assert cabi.plan_result(v3, 12, 4, win).how == "sret"
    arm = "aarch64-apple-darwin"
    assert [str(t) for t in cabi.plan_param(v3, 12, 4, arm).parts] == ["[3 x float]"]
    assert cabi.plan_param(pt + pt + pt, 48, 8, arm).how == "indirect"


def test_struct_with_a_heap_field_is_rejected():
    from greengold.diagnostics import CompileError
    src = "struct S:\n    name: string\n\nextern \"x.h\" fn f(s: S) -> i32\n\nfn main():\n    pass\n"
    with pytest.raises(CompileError) as err:
        compile_to_ir(src)
    assert any("cannot be passed to C by value" in d.message for d in err.value.diagnostics)


BINDGEN_C = r"""
#include <stdint.h>
typedef struct { unsigned ready : 1; unsigned mode : 3; unsigned level : 4; int count; } Flags;
typedef int (*int_fn)(int);
typedef struct { double x, y; } Vec2;
enum Color { RED, GREEN = 5, BLUE };
int flags_mode(Flags f) { return f.mode * 100 + f.level * 10 + f.ready; }
int apply_twice(int_fn f, int x) { return f(f(x)); }
Vec2 vec_add(Vec2 a, Vec2 b) { Vec2 r = { a.x + b.x, a.y + b.y }; return r; }
int color_code(int c) { return c == BLUE ? 66 : 0; }
"""


@pytest.mark.skipif(not HAS_CC, reason="needs a C compiler")
def test_bindgen_output_runs_with_callbacks_bitfields_and_structs():
    from greengold.bindgen import bindgen
    header = "\n".join(line.split("{")[0].rstrip() + ";" if "(" in line and "{ return" in line or "{ Vec2 r" in line
                       else line for line in BINDGEN_C.splitlines())
    out = bindgen(header)
    assert "bits: u32  # ready: bits 0..0, mode: bits 1..3, level: bits 4..7" in out
    assert "fn apply_twice(f: fn(i32) -> i32, x: i32) -> i32" in out
    assert "enum Color:" in out and "    BLUE = 6" in out
    src = out + """
fn inc(x: i32) -> i32:
    return x + 1

fn main():
    unsafe:
        f = Flags{ bits: 1 | (3 << 1) | (9 << 4), count: 0 }
        v = vec_add(Vec2{ x: 1.0, y: 2.0 }, Vec2{ x: 0.5, y: 0.25 })
        print(flags_mode(f), apply_twice(inc, 5), v.x, v.y, color_code(i32(Color.BLUE)))
"""
    r = run_built(src, extra_c=BINDGEN_C)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "391 7 1.5 2.25 66"
