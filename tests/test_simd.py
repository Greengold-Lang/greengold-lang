"""SIMD vector types."""
import pytest

from greengold.cli import compile_to_ir

from .helpers import messages, run_built

PROGRAM = """fn axpy(a: f32, xs: []f32, ys: lend []f32):
    av = f32x4.splat(a)
    i: usize = 0
    while i + 4 <= xs.len:
        y = f32x4.load(xs, i) * av + f32x4.load(ys, i)
        y.store(ys, i)
        i += 4

fn main():
    v = f32x4(1.0, 2.0, 3.0, 4.0)
    w = f32x4.splat(0.5)
    print(v + w, (v * w).sum(), v.lane(2), v.with_lane(0, 9.0))
    print(v.min(w), v.max(w), f32x4(4.0, 9.0, 16.0, 25.0).sqrt())
    a = i32x4(1, 2, 3, 4)
    print(a * a, (a & i32x4.splat(1)), u8x16.splat(255) + u8x16.splat(1))
    xs: [8]f32 = [1.0; 8]
    ys: [8]f32 = [2.0; 8]
    axpy(3.0, xs, ys)
    print(ys)
"""


def test_simd_program():
    res = run_built(PROGRAM)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "[1.5, 2.5, 3.5, 4.5] 5 3 [9, 2, 3, 4]",
        "[0.5, 0.5, 0.5, 0.5] [1, 2, 3, 4] [2, 3, 4, 5]",
        "[1, 4, 9, 16] [1, 0, 1, 0] [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]",
        "[5, 5, 5, 5, 5, 5, 5, 5]",
    ]


def test_vector_instructions_are_emitted():
    ir_text = compile_to_ir(PROGRAM)
    assert "fmul <4 x float>" in ir_text and "fadd <4 x float>" in ir_text


def test_load_past_end_panics():
    res = run_built("fn main():\n    xs: [3]f32 = [1.0; 3]\n    v = f32x4.load(xs, 0)\n    print(v)\n")
    assert res.returncode != 0
    assert "past the end" in res.stderr


@pytest.mark.parametrize("body, text", [
    ("print(f32x4.splat(1.0) + f32x8.splat(1.0))", "same vector type"),
    ("print(i32x4.splat(4) / i32x4.splat(2))", "is not defined on `i32x4`"),
    ("print(f32x4(1.0, 2.0))", "takes 4 values"),
    ("print(f32x4.splat(1.0).bogus())", "has no method named `bogus`"),
])
def test_simd_errors(body, text):
    msgs = messages(f"fn main():\n    {body}\n")
    assert any(text in m for m in msgs), msgs
