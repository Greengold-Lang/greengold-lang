"""Qwen3 architecture and K-quant weights in std.llama, against numpy."""
import struct

import numpy as np
import pytest

from .gguf_writer import GGML_F32, kv_f32, kv_str, kv_u32, write_gguf
from .helpers import HAS_CC, run_built
from .test_kquant import dequant_q4k, dequant_q6k, q8k_dequant

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

GGML_Q4_K, GGML_Q6_K = 12, 14
TOKENS = [5, 17, 3, 22, 9]
EPS = 1e-6


def q4k_blocks(rng, n, d):
    out = bytearray()
    for _ in range(n):
        out += struct.pack("<ee", d, d / 2) + bytes(rng.integers(0, 256, 12, dtype=np.uint8))
        out += bytes(rng.integers(0, 256, 128, dtype=np.uint8))
    return bytes(out)


def q6k_blocks(rng, n, d):
    out = bytearray()
    for _ in range(n):
        out += bytes(rng.integers(0, 256, 192, dtype=np.uint8)) + bytes(rng.integers(-30, 30, 16, dtype=np.int8))
        out += struct.pack("<e", d)
    return bytes(out)


class Cfg:
    def __init__(self, arch, dim, heads, kv, head_dim, hidden, layers, vocab, base=10000.0):
        self.arch, self.dim, self.heads, self.kv, self.hd = arch, dim, heads, kv, head_dim
        self.hidden, self.layers, self.vocab, self.base = hidden, layers, vocab, base
        self.q_dim = heads * head_dim
        self.qwen = arch == "qwen3"


def make_model(cfg, formats, seed=1):
    """Weights as (gguf type, bytes) plus the float matrices the model really has."""
    rng = np.random.default_rng(seed)
    tensors, mats = [], {}

    def add_matrix(name, rows, cols, fmt):
        if fmt == "f32":
            m = (rng.standard_normal((rows, cols)) * 0.12).astype(np.float32)
            tensors.append((name + ".weight", [cols, rows], GGML_F32, m.tobytes()))
        else:
            n = rows * cols // 256
            if fmt == "q4k":
                blob, kind, deq, size = q4k_blocks(rng, n, 0.0002), GGML_Q4_K, dequant_q4k, 144
            else:
                blob, kind, deq, size = q6k_blocks(rng, n, 0.0001), GGML_Q6_K, dequant_q6k, 210
            m = np.concatenate([deq(blob[i * size:(i + 1) * size]) for i in range(n)]).reshape(rows, cols)
            tensors.append((name + ".weight", [cols, rows], kind, blob))
        mats[name] = m.astype(np.float64)

    def add_vector(name, n):
        v = (1 + 0.1 * rng.standard_normal(n)).astype(np.float32)
        tensors.append((name + ".weight", [n], GGML_F32, v.tobytes()))
        mats[name] = v.astype(np.float64)

    add_matrix("token_embd", cfg.vocab, cfg.dim, formats["embd"])
    add_vector("output_norm", cfg.dim)
    add_matrix("output", cfg.vocab, cfg.dim, formats["output"])
    for l in range(cfg.layers):
        p = f"blk.{l}."
        add_vector(p + "attn_norm", cfg.dim)
        add_matrix(p + "attn_q", cfg.q_dim, cfg.dim, formats["q"])
        add_matrix(p + "attn_k", cfg.kv * cfg.hd, cfg.dim, formats["k"])
        add_matrix(p + "attn_v", cfg.kv * cfg.hd, cfg.dim, formats["v"])
        add_matrix(p + "attn_output", cfg.dim, cfg.q_dim, formats["o"])
        if cfg.qwen:
            add_vector(p + "attn_q_norm", cfg.hd)
            add_vector(p + "attn_k_norm", cfg.hd)
        add_vector(p + "ffn_norm", cfg.dim)
        add_matrix(p + "ffn_gate", cfg.hidden, cfg.dim, formats["gate"])
        add_matrix(p + "ffn_up", cfg.hidden, cfg.dim, formats["up"])
        add_matrix(p + "ffn_down", cfg.dim, cfg.hidden, formats["down"])
    a = cfg.arch
    kvs = [kv_str("general.architecture", a), kv_u32(f"{a}.context_length", 64), kv_u32(f"{a}.embedding_length", cfg.dim),
           kv_u32(f"{a}.block_count", cfg.layers), kv_u32(f"{a}.feed_forward_length", cfg.hidden),
           kv_u32(f"{a}.attention.head_count", cfg.heads), kv_u32(f"{a}.attention.head_count_kv", cfg.kv),
           kv_f32(f"{a}.rope.freq_base", cfg.base), kv_f32(f"{a}.attention.layer_norm_rms_epsilon", EPS)]
    if cfg.qwen:
        kvs.append(kv_u32(f"{a}.attention.key_length", cfg.hd))
    return write_gguf(kvs, tensors), mats


def reference(cfg, w, tokens, quantize_acts=False):
    qa = (lambda v: q8k_dequant(v.astype(np.float32)).astype(np.float64)) if quantize_acts else (lambda v: v)
    hd, half = cfg.hd, cfg.hd // 2
    freq = cfg.base ** (-2.0 * np.arange(half) / hd)

    def rms(x, g):
        return x / np.sqrt(np.mean(x * x) + EPS) * g

    def head_norm(x, heads, g):
        return np.stack([rms(h, g) for h in x.reshape(heads, hd)])

    def rope(x, pos):
        x = x.copy()
        c, s = np.cos(pos * freq), np.sin(pos * freq)
        if cfg.qwen:  # pairs (i, i + half)
            a, b = x[:, :half].copy(), x[:, half:].copy()
            x[:, :half], x[:, half:] = a * c - b * s, a * s + b * c
        else:
            a, b = x[:, 0::2].copy(), x[:, 1::2].copy()
            x[:, 0::2], x[:, 1::2] = a * c - b * s, a * s + b * c
        return x

    caches = [([], []) for _ in range(cfg.layers)]
    logits = []
    for pos, tok in enumerate(tokens):
        x = w["token_embd"][tok].copy()
        for l in range(cfg.layers):
            p = f"blk.{l}."
            xb = rms(x, w[p + "attn_norm"])
            xq = qa(xb)
            q = (w[p + "attn_q"] @ xq).reshape(cfg.heads, hd)
            k = (w[p + "attn_k"] @ xq).reshape(cfg.kv, hd)
            v = (w[p + "attn_v"] @ xq).reshape(cfg.kv, hd)
            if cfg.qwen:
                q = head_norm(q, cfg.heads, w[p + "attn_q_norm"])
                k = head_norm(k, cfg.kv, w[p + "attn_k_norm"])
            q, k = rope(q, pos), rope(k, pos)
            caches[l][0].append(k)
            caches[l][1].append(v)
            ks, vs = np.stack(caches[l][0]), np.stack(caches[l][1])
            att = np.zeros((cfg.heads, hd))
            for h in range(cfg.heads):
                g = h // (cfg.heads // cfg.kv)
                sc = ks[:, g] @ q[h] / np.sqrt(hd)
                pr = np.exp(sc - sc.max())
                att[h] = (pr / pr.sum()) @ vs[:, g]
            x = x + w[p + "attn_output"] @ qa(att.reshape(-1))
            xb = rms(x, w[p + "ffn_norm"])
            xq = qa(xb)
            gate, up = w[p + "ffn_gate"] @ xq, w[p + "ffn_up"] @ xq
            x = x + w[p + "ffn_down"] @ qa(gate / (1 + np.exp(-gate)) * up)
        logits.append(w["output"] @ qa(rms(x, w["output_norm"])))
    return np.array(logits)


PROGRAM = """import std.llama
import std.parallel

fn main():
    model = llama.Model.load("PATH").value_or_panic()
    pool = parallel.Pool.new(3)
    st = llama.State.new(model.cfg, 32)
    toks: [5]i32 = [5, 17, 3, 22, 9]
    for p in 0..5:
        llama.forward(model, st, pool, toks[p], p)
        for i in 0..st.logits.len():
            print(f64(st.logits[i]))
"""


def run(tmp_path, blob, cfg):
    path = tmp_path / "m.gguf"
    path.write_bytes(blob)
    res = run_built(PROGRAM.replace("PATH", path.as_posix()), release=True, timeout=180)
    assert res.returncode == 0, res.stderr
    return np.array([float(t) for t in res.stdout.split()]).reshape(len(TOKENS), cfg.vocab)


def test_qwen3_f32_model_matches_numpy(tmp_path):
    cfg = Cfg("qwen3", dim=64, heads=4, kv=2, head_dim=24, hidden=96, layers=2, vocab=48, base=1000000.0)
    fmts = {k: "f32" for k in ("embd", "output", "q", "k", "v", "o", "gate", "up", "down")}
    blob, w = make_model(cfg, fmts)
    got = run(tmp_path, blob, cfg)
    np.testing.assert_allclose(got, reference(cfg, w, TOKENS), rtol=3e-3, atol=3e-3)


@pytest.mark.parametrize("arch", ["llama", "qwen3"])
def test_kquant_model_is_close_to_numpy(tmp_path, arch):
    cfg = Cfg(arch, dim=256, heads=4, kv=2, head_dim=64, hidden=512, layers=2, vocab=40)
    fmts = {"embd": "q6k", "output": "q6k", "q": "q4k", "k": "q4k", "v": "q6k", "o": "q4k",
            "gate": "q4k", "up": "q4k", "down": "q6k"}
    blob, w = make_model(cfg, fmts, seed=2)
    got = run(tmp_path, blob, cfg)
    # the reference quantizes each activation to Q8_K as the kernels do; what is left is float rounding
    want = reference(cfg, w, TOKENS, quantize_acts=True)
    np.testing.assert_allclose(got, want, rtol=1e-2, atol=1e-2)
    # without that rounding the logits differ by the quantization noise of the activations (a random model amplifies it)
    exact = reference(cfg, w, TOKENS)
    assert np.abs(got - exact).max() < 0.6 * np.abs(exact).max()


def test_unsupported_types_are_named(tmp_path):
    cfg = Cfg("llama", dim=64, heads=4, kv=2, head_dim=16, hidden=96, layers=1, vocab=16)
    fmts = {k: "f32" for k in ("embd", "output", "q", "k", "v", "o", "gate", "up", "down")}
    blob, _ = make_model(cfg, fmts)
    # turn the type of attn_q into 13 (Q5_K), which is not supported
    marker = b"blk.0.attn_q.weight"
    i = blob.index(marker) + len(marker)
    n_dims = struct.unpack("<I", blob[i:i + 4])[0]
    t = i + 4 + 8 * n_dims
    blob = blob[:t] + struct.pack("<I", 13) + blob[t + 4:]
    path = tmp_path / "bad.gguf"
    path.write_bytes(blob)
    res = run_built(f"""import std.llama

fn main():
    match llama.Model.load("{path.as_posix()}"):
        Ok(m):
            print("loaded?")
        Err(e):
            print(e)
""")
    assert res.returncode == 0, res.stderr
    assert "q5_K" in res.stdout and "blk.0.attn_q.weight" in res.stdout
