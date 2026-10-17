"""std.kquant: Q4_K and Q6_K against a plain Python implementation of the ggml dequantization loops."""
import struct

import numpy as np
import pytest

from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

ROWS, COLS = 6, 512  # two super-blocks per row
NB = COLS // 256


def f16(x: float) -> bytes:
    return struct.pack("<e", x)


def random_q4k(rng, n):
    out = bytearray()
    for _ in range(n):
        out += f16(rng.choice([0.01, 0.02, 0.005])) + f16(rng.choice([0.01, 0.003, 0.02]))
        out += bytes(rng.integers(0, 256, 12, dtype=np.uint8)) + bytes(rng.integers(0, 256, 128, dtype=np.uint8))
    return bytes(out)


def random_q6k(rng, n):
    out = bytearray()
    for _ in range(n):
        out += bytes(rng.integers(0, 256, 192, dtype=np.uint8))  # ql, qh
        out += bytes(rng.integers(-40, 40, 16, dtype=np.int8))   # scales
        out += f16(rng.choice([0.01, 0.02, 0.005]))
    return bytes(out)


def scale_min_k4(j, q):
    if j < 4:
        return q[j] & 63, q[j + 4] & 63
    return (q[j + 4] & 0xF) | ((q[j - 4] >> 6) << 4), (q[j + 4] >> 4) | ((q[j] >> 6) << 4)


def dequant_q4k(block: bytes) -> np.ndarray:
    d, dmin = struct.unpack("<ee", block[:4])
    scales, qs = block[4:16], block[16:144]
    y, is_, q = [], 0, 0
    for _ in range(0, 256, 64):
        sc, m = scale_min_k4(is_, scales)
        d1, m1 = d * sc, dmin * m
        sc, m = scale_min_k4(is_ + 1, scales)
        d2, m2 = d * sc, dmin * m
        y += [d1 * (qs[q + l] & 0xF) - m1 for l in range(32)]
        y += [d2 * (qs[q + l] >> 4) - m2 for l in range(32)]
        q += 32
        is_ += 2
    return np.array(y)


def dequant_q6k(block: bytes) -> np.ndarray:
    ql, qh = block[:128], block[128:192]
    sc = struct.unpack("<16b", block[192:208])
    d = struct.unpack("<e", block[208:210])[0]
    y = np.zeros(256)
    for n in range(0, 256, 128):
        o, p, s = n // 2, n // 4, n // 16
        for l in range(32):
            i = l // 16
            q1 = ((ql[o + l] & 0xF) | (((qh[p + l] >> 0) & 3) << 4)) - 32
            q2 = ((ql[o + l + 32] & 0xF) | (((qh[p + l] >> 2) & 3) << 4)) - 32
            q3 = ((ql[o + l] >> 4) | (((qh[p + l] >> 4) & 3) << 4)) - 32
            q4 = ((ql[o + l + 32] >> 4) | (((qh[p + l] >> 6) & 3) << 4)) - 32
            y[n + l] = d * sc[s + i] * q1
            y[n + l + 32] = d * sc[s + i + 2] * q2
            y[n + l + 64] = d * sc[s + i + 4] * q3
            y[n + l + 96] = d * sc[s + i + 6] * q4
    return y


def activation(n):
    return np.array([np.float32(((i * 37 + 5) % 101) / 50.0 - 1.0) for i in range(n)], dtype=np.float32)


def q8k_dequant(x):
    out = []
    for blk in x.reshape(-1, 256):
        amax = float(np.abs(blk).max())
        d = np.float32(amax / 127.0)
        idv = np.float32(1.0 / d) if d != 0 else np.float32(0)
        q = np.floor(blk * idv + np.float32(0.5))
        out.append(q * d)
    return np.concatenate(out)


PROGRAM = """import std.kquant
import std.mmap
import std.parallel

fn main():
    f = mmap.MappedFile.open("PATH").value_or_panic()
    rows: usize = 6
    cols: usize = 512
    x = List[f32]()
    for i in 0..cols:
        x.push(f32((i * 37 + 5) % 101) / 50.0 - 1.0)
    xq = kquant.quantize_q8k(x[..])
    xd = xq.dequantize()
    for i in 0..cols:
        print(f64(xd[i]))
    pool = parallel.Pool.new(3)
    y = List[f32]()
    yp = List[f32]()
    for r in 0..rows:
        y.push(0.0)
        yp.push(0.0)
    bytes = f.bytes()
    unsafe:
        if KIND == 4:
            w = slice_from_raw[kquant.BlockQ4K](ptr_cast[*kquant.BlockQ4K](addr(bytes)), rows * cols / 256)
            kquant.q4k_matvec(w, rows, cols, xq, y[..])
            kquant.q4k_matvec_parallel(pool, w, rows, cols, xq, yp[..])
            for r in 0..rows:
                row = kquant.dequantize_row_q4k(w, cols, r)
                for c in 0..cols:
                    print(f64(row[c]))
        else:
            w = slice_from_raw[kquant.BlockQ6K](ptr_cast[*kquant.BlockQ6K](addr(bytes)), rows * cols / 256)
            kquant.q6k_matvec(w, rows, cols, xq, y[..])
            kquant.q6k_matvec_parallel(pool, w, rows, cols, xq, yp[..])
            for r in 0..rows:
                row = kquant.dequantize_row_q6k(w, cols, r)
                for c in 0..cols:
                    print(f64(row[c]))
    for r in 0..rows:
        print(f64(y[r]))
    for r in 0..rows:
        print(f64(yp[r]))
"""


@pytest.mark.parametrize("kind", [4, 6])
@pytest.mark.parametrize("cpu", ["", "native"])
def test_kquant_matches_reference(tmp_path, kind, cpu):
    from greengold import llvm_driver
    rng = np.random.default_rng(kind)
    blob = random_q4k(rng, ROWS * NB) if kind == 4 else random_q6k(rng, ROWS * NB)
    path = tmp_path / "w.bin"
    path.write_bytes(blob)
    size = 144 if kind == 4 else 210
    deq = dequant_q4k if kind == 4 else dequant_q6k
    llvm_driver.set_cpu(cpu or None)
    try:
        res = run_built(PROGRAM.replace("PATH", path.as_posix()).replace("KIND", str(kind)), release=True, timeout=120)
    finally:
        llvm_driver.set_cpu(None)
    assert res.returncode == 0, res.stderr
    vals = np.array([float(t) for t in res.stdout.split()])
    xd = vals[:COLS]
    rows = vals[COLS:COLS + ROWS * COLS].reshape(ROWS, COLS)
    y = vals[COLS + ROWS * COLS:COLS + ROWS * COLS + ROWS]
    yp = vals[COLS + ROWS * COLS + ROWS:]
    np.testing.assert_allclose(xd, q8k_dequant(activation(COLS)), rtol=1e-6, atol=1e-7)
    want_rows = np.array([np.concatenate([deq(blob[(r * NB + b) * size:(r * NB + b + 1) * size]) for b in range(NB)])
                          for r in range(ROWS)])
    np.testing.assert_allclose(rows, want_rows, rtol=1e-5, atol=1e-6)
    want_y = want_rows @ xd
    np.testing.assert_allclose(y, want_y, rtol=1e-4, atol=1e-4 * np.abs(want_y).max())
    np.testing.assert_array_equal(y, yp)


MATMUL = """import std.kquant
import std.mmap
import std.parallel

fn main():
    f = mmap.MappedFile.open("PATH").value_or_panic()
    rows: usize = 6
    cols: usize = 512
    nvec: usize = 7
    x = List[f32]()
    for i in 0..cols * nvec:
        x.push(f32((i * 37 + 5 + (i / 512) * 11) % 101) / 50.0 - 1.0)
    xq = kquant.quantize_q8k(x[..])
    pool = parallel.Pool.new(3)
    ys = List[f32]()
    for i in 0..rows * nvec:
        ys.push(0.0)
    bytes = f.bytes()
    worst: f32 = 0.0
    unsafe:
        if KIND == 4:
            w = slice_from_raw[kquant.BlockQ4K](ptr_cast[*kquant.BlockQ4K](addr(bytes)), rows * cols / 256)
            kquant.q4k_matmul_parallel(pool, w, rows, cols, nvec, xq, ys[..])
            for a in 0..nvec:
                one = kquant.quantize_q8k(x[a * cols..(a + 1) * cols])
                y = List[f32]()
                for r in 0..rows:
                    y.push(0.0)
                kquant.q4k_matvec(w, rows, cols, one, y[..])
                for r in 0..rows:
                    d = y[r] - ys[a * rows + r]
                    if d < 0.0:
                        d = 0.0 - d
                    if d > worst:
                        worst = d
        else:
            w = slice_from_raw[kquant.BlockQ6K](ptr_cast[*kquant.BlockQ6K](addr(bytes)), rows * cols / 256)
            kquant.q6k_matmul_parallel(pool, w, rows, cols, nvec, xq, ys[..])
            for a in 0..nvec:
                one = kquant.quantize_q8k(x[a * cols..(a + 1) * cols])
                y = List[f32]()
                for r in 0..rows:
                    y.push(0.0)
                kquant.q6k_matvec(w, rows, cols, one, y[..])
                for r in 0..rows:
                    d = y[r] - ys[a * rows + r]
                    if d < 0.0:
                        d = 0.0 - d
                    if d > worst:
                        worst = d
    print(f64(worst), f64(ys[0]), f64(ys[rows * nvec - 1]))
"""


@pytest.mark.parametrize("kind", [4, 6])
def test_matmul_of_seven_vectors_equals_seven_matvecs(tmp_path, kind):
    rng = np.random.default_rng(kind + 10)
    blob = random_q4k(rng, ROWS * NB) if kind == 4 else random_q6k(rng, ROWS * NB)
    path = tmp_path / "w.bin"
    path.write_bytes(blob)
    res = run_built(MATMUL.replace("PATH", path.as_posix()).replace("KIND", str(kind)), release=True, timeout=120)
    assert res.returncode == 0, res.stderr
    worst, first, last = (float(t) for t in res.stdout.split())
    assert worst == 0.0 and abs(first) + abs(last) > 0
