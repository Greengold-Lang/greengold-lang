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


DOT = """fn dot(x: []i8, w: []i8) -> i32:
    acc = i32x4.splat(0)
    i: usize = 0
    while i + 16 <= x.len:
        acc = acc.dot_i8(i8x16.load(x, i), i8x16.load(w, i))
        i += 16
    return acc.sum()

fn dot8(x: []i8, w: []i8) -> i32:
    acc = i32x8.splat(0)
    i: usize = 0
    while i + 32 <= x.len:
        acc = acc.dot_i8(i8x32.load(x, i), i8x32.load(w, i))
        i += 32
    return acc.sum()

fn main():
    x: [64]i8 = [0; 64]
    w: [64]i8 = [0; 64]
    for i in 0..64:
        x[i] = i8(i - 20)
        w[i] = i8(3 * i % 11 - 5)
    print(dot(x, w), dot8(x, w))
    print(i32x4.splat(1).dot_u8i8(u8x16.splat(200), i8x16.splat(-1)))
    print(i32x4(0, 0, 0, 0).dot_i8(i8x16(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16), i8x16.splat(1)))
    f = f32x8.splat(2.0)
    print(f.fma(f32x8.splat(3.0), f32x8.splat(1.0)))
"""


def _expected_dot():
    xs = [i - 20 for i in range(64)]
    ws = [3 * i % 11 - 5 for i in range(64)]
    return sum(a * b for a, b in zip(xs, ws))


@pytest.mark.parametrize("cpu", ["", "x86-64-v3", "native"])
def test_dot_and_fma(cpu):
    from greengold import llvm_driver
    want = _expected_dot()
    groups = [(1, 2, 9, 10), (3, 4, 11, 12), (5, 6, 13, 14), (7, 8, 15, 16)]
    llvm_driver.set_cpu(cpu or None)
    try:
        res = run_built(DOT)
    finally:
        llvm_driver.set_cpu(None)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        f"{want} {want}",
        "[-799, -799, -799, -799]",
        "[" + ", ".join(str(sum(g)) for g in groups) + "]",
        "[7, 7, 7, 7, 7, 7, 7, 7]",
    ]


def test_cpu_changes_the_machine_code():
    from pathlib import Path

    from greengold import llvm_driver
    from greengold.codegen_llvm import native_triple
    triple = native_triple(None)
    if not triple.startswith("x86_64"):
        pytest.skip("x86 only")
    ir_text = compile_to_ir((Path(__file__).parent.parent / "benchmarks" / "qmatvec.gg").read_text(encoding="utf-8"),
                            release=True)
    asm = {}
    for cpu in (None, "x86-64-v3"):
        llvm_driver.set_cpu(cpu)
        try:
            mod, tm = llvm_driver.compile_ir(ir_text, triple, True)
            asm[cpu] = tm.emit_assembly(mod)
        finally:
            llvm_driver.set_cpu(None)
    assert "ymm" not in asm[None]
    assert "vpmaddwd" in asm["x86-64-v3"] and "ymm" in asm["x86-64-v3"]
