"""std.tensor: f16, Tensor, and the q8_0 / q4_0 matrices."""
import struct

import pytest

from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

F16_VALUES = [0.0, 1.0, -2.5, 0.333251953125, 65504.0, 6.1e-5, 1e-7, 3.14159, -0.0009765625, 1234.5678, 5.96e-8,
              70000.0, 0.1, 2049.0, 2051.0]


def test_f16_matches_ieee_half():
    src = "import std.tensor\n\nfn main():\n"
    for v in F16_VALUES:
        src += f"    h = tensor.f32_to_f16(f32({v!r}))\n    print(h, tensor.f16_to_f32(h), tensor.f16_scale(h))\n"
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.splitlines()
    for v, line in zip(F16_VALUES, lines):
        f32v = struct.unpack("<f", struct.pack("<f", v))[0]
        try:
            want = struct.unpack("<H", struct.pack("<e", f32v))[0]
        except OverflowError:
            want = 0x7C00  # beyond the half range: infinity
        h = int(line.split()[0])
        assert h == want, (v, h, want)
        if want != 0x7C00:
            back = struct.unpack("<e", struct.pack("<H", want))[0]
            got = [float(t) for t in line.split()[1:]]
            assert got[0] == pytest.approx(back, rel=1e-5, abs=1e-12), line
            assert got[1] == pytest.approx(back, rel=1e-5, abs=1e-12), line


MATRIX = """import std.tensor
import std.parallel

fn abs32(x: f32) -> f32:
    if x < 0.0:
        return 0.0 - x
    return x

fn main():
    rows: usize = 70
    cols: usize = 96
    print(size_of[tensor.BlockQ8](), size_of[tensor.BlockQ4]())
    t = tensor.Tensor.new([rows, cols])
    state: u64 = 7
    for r in 0..rows:
        for c in 0..cols:
            overflow: wrap
            state = state * 6364136223846793005 + 1442695040888963407
            t.set(r, c, f32(i64((state >> 33) % 2001) - 1000) / 1000.0)
    x = List[f32]()
    for c in 0..cols:
        x.push(f32((c * 37) % 101) / 50.0 - 1.0)
    xq = tensor.quantize_q8(x[..])
    xd = xq.dequantize()
    q4 = tensor.Q4Matrix.quantize(t)
    q8 = tensor.Q8Matrix.quantize(t)
    y4 = List[f32]()
    y8 = List[f32]()
    p4 = List[f32]()
    p8 = List[f32]()
    for r in 0..rows:
        y4.push(0.0)
        y8.push(0.0)
        p4.push(0.0)
        p8.push(0.0)
    q4.matvec(xq, y4[..])
    q8.matvec(xq, y8[..])
    pool = parallel.Pool.new(3)
    q4.matvec_parallel(pool, xq, p4[..])
    q8.matvec_parallel(pool, xq, p8[..])
    kernel4: f32 = 0.0
    quant4: f32 = 0.0
    quant8: f32 = 0.0
    same = true
    for r in 0..rows:
        row = q4.dequantize_row(r)
        ref4: f32 = 0.0
        exact: f32 = 0.0
        for c in 0..cols:
            ref4 += row[c] * xd[c]
            exact += t.at(r, c) * x[c]
        if abs32(ref4 - y4[r]) > kernel4:
            kernel4 = abs32(ref4 - y4[r])
        if abs32(exact - y4[r]) > quant4:
            quant4 = abs32(exact - y4[r])
        if abs32(exact - y8[r]) > quant8:
            quant8 = abs32(exact - y8[r])
        if y4[r] != p4[r] or y8[r] != p8[r]:
            same = false
    print(kernel4 < 0.0001, quant4 < 1.0, quant8 < 0.1, same)
    t.reshape([rows * cols])
    print(t.rank(), t.len(), t.dim(0))
"""


@pytest.mark.parametrize("release, cpu", [(False, ""), (True, ""), (True, "x86-64-v2"), (True, "native")])
def test_quantized_matvec(release, cpu):
    from greengold import llvm_driver
    llvm_driver.set_cpu(cpu or None)
    try:
        res = run_built(MATRIX, release=release, timeout=60)
    finally:
        llvm_driver.set_cpu(None)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["34 18", "true true true true", "1 6720 6720"]
