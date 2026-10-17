"""Builds GGUF files for tests."""
import struct

import numpy as np

STRING, U32, I32, F32, BOOL, ARRAY, U64 = 8, 4, 5, 6, 7, 9, 10
GGML_F32, GGML_F16, GGML_Q4_0, GGML_Q8_0 = 0, 1, 2, 8


def gstr(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def kv_str(key, value):
    return gstr(key) + struct.pack("<I", STRING) + gstr(value)


def kv_u32(key, value):
    return gstr(key) + struct.pack("<I", U32) + struct.pack("<I", value)


def kv_f32(key, value):
    return gstr(key) + struct.pack("<I", F32) + struct.pack("<f", value)


def kv_bool(key, value):
    return gstr(key) + struct.pack("<I", BOOL) + bytes([1 if value else 0])


def kv_str_array(key, values):
    return gstr(key) + struct.pack("<IIQ", ARRAY, STRING, len(values)) + b"".join(gstr(v) for v in values)


def kv_f32_array(key, values):
    return gstr(key) + struct.pack("<IIQ", ARRAY, F32, len(values)) + struct.pack(f"<{len(values)}f", *values)


def kv_i32_array(key, values):
    return gstr(key) + struct.pack("<IIQ", ARRAY, I32, len(values)) + struct.pack(f"<{len(values)}i", *values)


def write_gguf(kvs: list[bytes], tensors: list[tuple[str, list[int], int, bytes]], alignment: int = 32) -> bytes:
    """`tensors`: (name, dims in file order, ggml type, data)."""
    header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", len(tensors), len(kvs)) + b"".join(kvs)
    offset, data = 0, b""
    for name, dims, kind, blob in tensors:
        header += gstr(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims)
        header += struct.pack("<I", kind) + struct.pack("<Q", offset)
        pad = (-len(blob)) % alignment
        data += blob + b"\0" * pad
        offset += len(blob) + pad
    header += b"\0" * ((-len(header)) % alignment)
    return header + data


def quantize_q8_0(x: np.ndarray) -> bytes:
    """ggml's q8_0 of a float array (length a multiple of 32), exactly as std.tensor does it."""
    out = bytearray()
    for block in x.astype(np.float32).reshape(-1, 32):
        amax = float(np.abs(block).max())
        d = amax / 127.0
        idv = 1.0 / d if d != 0 else 0.0
        q = np.floor(block * np.float32(idv) + np.float32(0.5)).astype(np.int8)
        out += struct.pack("<e", d) + q.tobytes()
    return bytes(out)


def dequantize_q8_0(blob: bytes, n: int) -> np.ndarray:
    out = np.empty(n, dtype=np.float32)
    for b in range(n // 32):
        chunk = blob[b * 34:(b + 1) * 34]
        d = struct.unpack("<e", chunk[:2])[0]
        out[b * 32:(b + 1) * 32] = d * np.frombuffer(chunk[2:], dtype=np.int8).astype(np.float32)
    return out
