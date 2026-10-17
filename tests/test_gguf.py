"""std.mmap and std.gguf: memory-mapped files and GGUF model files."""
import random
import struct

import pytest

from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")


def _s(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def make_gguf(version: int = 3) -> bytes:
    rng = random.Random(5)
    kvs = [
        ("general.architecture", 8, _s("llama")),
        ("llama.block_count", 4, struct.pack("<I", 2)),
        ("llama.rope.freq_base", 6, struct.pack("<f", 10000.0)),
        ("general.flag", 7, b"\x01"),
        ("neg", 5, struct.pack("<i", -7)),
        ("tokenizer.tokens", 9, struct.pack("<IQ", 8, 3) + _s("a") + _s("bb") + _s("ccc")),
        ("numbers", 9, struct.pack("<IQ", 4, 3) + struct.pack("<3I", 1, 2, 3)),
        ("general.name", 8, _s("tiny")),
    ]
    q4 = bytearray()
    for _ in range(5 * 2):  # 5 rows of 64 columns: 2 blocks per row
        q4 += struct.pack("<e", rng.choice([0.5, 0.25, 0.125])) + bytes(rng.randrange(256) for _ in range(16))
    q8 = bytearray()
    for _ in range(2):
        q8 += struct.pack("<e", 0.01) + bytes(rng.randrange(256) for _ in range(32))
    f32 = struct.pack("<3f", 1.5, -2.0, 4.25)
    tensors = [("w", [64, 5], 2, bytes(q4)), ("q8", [32, 2], 8, bytes(q8)), ("v", [3], 0, f32)]
    header = b"GGUF" + struct.pack("<I", version) + struct.pack("<QQ", len(tensors), len(kvs))
    for key, kind, value in kvs:
        header += _s(key) + struct.pack("<I", kind) + value
    offset = 0
    data = b""
    for name, dims, kind, blob in tensors:
        header += _s(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims)
        header += struct.pack("<I", kind) + struct.pack("<Q", offset)
        pad = (-len(blob)) % 32
        data += blob + b"\0" * pad
        offset += len(blob) + pad
    header += b"\0" * ((-len(header)) % 32)
    return header + data


PROGRAM = """import std.gguf
import std.tensor

fn abs32(x: f32) -> f32:
    if x < 0.0:
        return 0.0 - x
    return x

fn main():
    match gguf.Gguf.open("PATH"):
        Err(e):
            print("error:", e)
        Ok(g):
            print(g.version, g.meta.len(), g.tensors.len())
            print(g.get_str("general.architecture").value_or_panic(), g.get_int("llama.block_count").value_or_panic(), g.get_float("llama.rope.freq_base").value_or_panic())
            print(g.get_int("general.flag").value_or_panic(), g.get_int("neg").value_or_panic(), g.get_str("general.name").value_or_panic())
            print(g.find_meta("missing").is_none(), g.meta[g.find_meta("tokenizer.tokens").value_or_panic()].count, g.meta[g.find_meta("numbers").value_or_panic()].count)
            i = g.find_tensor("w").value_or_panic()
            print(g.tensors[i].dims[0], g.tensors[i].dims[1], g.tensors[i].kind, g.tensors[i].count, g.tensors[i].size)
            v = g.f32_values(g.find_tensor("v").value_or_panic())
            print(v.len, v[0], v[1], v[2])
            q8 = g.q8_blocks(g.find_tensor("q8").value_or_panic())
            print(q8.len, tensor.f16_to_f32(q8[1].d))
            w = g.q4_blocks(i)
            x = List[f32]()
            for c in 0..64:
                x.push(f32((c * 7) % 13) / 6.0 - 1.0)
            xq = tensor.quantize_q8(x[..])
            xd = xq.dequantize()
            y = List[f32]()
            for r in 0..5:
                y.push(0.0)
            tensor.q4_matvec(w, 5, 64, xq, y[..])
            worst: f32 = 0.0
            for r in 0..5:
                row = tensor.dequantize_row_q4(w, 64, r)
                s: f32 = 0.0
                for c in 0..64:
                    s += row[c] * xd[c]
                if abs32(s - y[r]) > worst:
                    worst = abs32(s - y[r])
            print(worst < 0.001)
"""


def test_gguf_reads_header_and_views(tmp_path):
    path = tmp_path / "tiny.gguf"
    path.write_bytes(make_gguf())
    res = run_built(PROGRAM.replace("PATH", path.as_posix()))
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "3 8 3",
        "llama 2 10000",
        "1 -7 tiny",
        "true 3 3",
        "64 5 2 320 180",
        "3 1.5 -2 4.25",
        "2 0.0100021",
        "true",
    ]


def test_gguf_version_2(tmp_path):
    path = tmp_path / "v2.gguf"
    path.write_bytes(make_gguf(2))
    res = run_built(PROGRAM.replace("PATH", path.as_posix()))
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines()[0] == "2 8 3"


@pytest.mark.parametrize("name, blob, message", [
    ("magic", b"GGUX" + bytes(64), "not a GGUF file"),
    ("empty", b"", "not a GGUF file"),
    ("version", b"GGUF" + struct.pack("<I", 9) + bytes(32), "unsupported GGUF version"),
    ("cut", make_gguf()[:200], "cut short"),
    ("data", make_gguf()[:-40], "outside the file"),
])
def test_gguf_rejects_bad_files(tmp_path, name, blob, message):
    path = tmp_path / f"{name}.gguf"
    path.write_bytes(blob)
    res = run_built(PROGRAM.replace("PATH", path.as_posix()))
    assert res.returncode == 0, res.stderr
    assert message in res.stdout.splitlines()[0], res.stdout


def test_mmap_reads_a_file(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(bytes(range(256)) * 20)
    res = run_built(f"""import std.mmap

fn main():
    match mmap.MappedFile.open("{path.as_posix()}"):
        Ok(f):
            b = f.bytes()
            total: i64 = 0
            for i in 0..b.len:
                total += i64(b[i])
            print(f.len(), b[0], b[255], b[256], total)
        Err(e):
            print(e)
    match mmap.MappedFile.open("{(tmp_path / 'missing').as_posix()}"):
        Ok(f):
            print("?")
        Err(e):
            print(e)
    empty = "{(tmp_path / 'empty').as_posix()}"
""")
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [f"5120 0 255 0 {sum(range(256)) * 20}", "cannot open the file"]
