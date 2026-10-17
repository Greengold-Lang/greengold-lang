"""std.llama: a tiny random LLaMA model in GGUF, run by Greengold and by plain numpy."""
import numpy as np
import pytest

from .gguf_writer import (GGML_F32, GGML_Q8_0, dequantize_q8_0, kv_f32, kv_str, kv_u32, quantize_q8_0, write_gguf)
from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

DIM, HEADS, KV, HIDDEN, LAYERS, VOCAB, CTX = 64, 4, 2, 96, 2, 48, 64
HD = DIM // HEADS
EPS = 1e-5
BASE = 10000.0
TOKENS = [5, 17, 3, 40, 22, 9]


def make_weights(seed=3, vocab=VOCAB):
    rng = np.random.default_rng(seed)

    def mat(rows, cols, scale=0.15):
        return (rng.standard_normal((rows, cols)) * scale).astype(np.float32)

    w = {"token_embd": mat(vocab, DIM, 0.5), "output_norm": (1 + 0.1 * rng.standard_normal(DIM)).astype(np.float32),
         "output": mat(vocab, DIM)}
    for l in range(LAYERS):
        w[f"blk.{l}.attn_norm"] = (1 + 0.1 * rng.standard_normal(DIM)).astype(np.float32)
        w[f"blk.{l}.ffn_norm"] = (1 + 0.1 * rng.standard_normal(DIM)).astype(np.float32)
        w[f"blk.{l}.attn_q"] = mat(DIM, DIM)
        w[f"blk.{l}.attn_k"] = mat(KV * HD, DIM)
        w[f"blk.{l}.attn_v"] = mat(KV * HD, DIM)
        w[f"blk.{l}.attn_output"] = mat(DIM, DIM)
        w[f"blk.{l}.ffn_gate"] = mat(HIDDEN, DIM)
        w[f"blk.{l}.ffn_up"] = mat(HIDDEN, DIM)
        w[f"blk.{l}.ffn_down"] = mat(DIM, HIDDEN)
    return w


def build_gguf(w, quantized=False, tied=False, factors=None, extra_kvs=()):
    kvs = [kv_str("general.architecture", "llama"), kv_u32("llama.context_length", CTX),
           kv_u32("llama.embedding_length", DIM), kv_u32("llama.block_count", LAYERS),
           kv_u32("llama.feed_forward_length", HIDDEN), kv_u32("llama.attention.head_count", HEADS),
           kv_u32("llama.attention.head_count_kv", KV), kv_f32("llama.rope.freq_base", BASE),
           kv_f32("llama.attention.layer_norm_rms_epsilon", EPS), *extra_kvs]
    tensors = []
    for name, arr in w.items():
        if name == "output" and tied:
            continue
        is_norm = arr.ndim == 1
        gg_name = name + ".weight"
        if is_norm:
            tensors.append((gg_name, [arr.shape[0]], GGML_F32, arr.astype(np.float32).tobytes()))
        elif quantized:
            tensors.append((gg_name, [arr.shape[1], arr.shape[0]], GGML_Q8_0, quantize_q8_0(arr.reshape(-1))))
        else:
            tensors.append((gg_name, [arr.shape[1], arr.shape[0]], GGML_F32, arr.tobytes()))
    if factors is not None:
        tensors.append(("rope_freqs.weight", [HD // 2], GGML_F32, np.array(factors, dtype=np.float32).tobytes()))
    return write_gguf(kvs, tensors)


def effective(w, quantized):
    """The weights the model really has (after q8_0 rounding)."""
    if not quantized:
        return w
    out = {}
    for name, arr in w.items():
        if arr.ndim == 2:
            out[name] = dequantize_q8_0(quantize_q8_0(arr.reshape(-1)), arr.size).reshape(arr.shape)
        else:
            out[name] = arr
    return out


def reference(w, tokens, tied=False, factors=None):
    w = {k: v.astype(np.float64) for k, v in w.items()}
    out_w = w["token_embd"] if tied else w["output"]
    half = HD // 2
    freq = BASE ** (-2.0 * np.arange(half) / HD)
    if factors is not None:
        freq = freq / np.array(factors, dtype=np.float64)

    def rms(x, g):
        return x / np.sqrt(np.mean(x * x) + EPS) * g

    def rope(x, heads, pos):
        x = x.reshape(heads, HD).copy()
        c, s = np.cos(pos * freq), np.sin(pos * freq)
        a, b = x[:, 0::2].copy(), x[:, 1::2].copy()
        x[:, 0::2], x[:, 1::2] = a * c - b * s, a * s + b * c
        return x

    caches = [([], []) for _ in range(LAYERS)]
    logits = []
    for pos, tok in enumerate(tokens):
        x = w["token_embd"][tok].copy()
        for l in range(LAYERS):
            xb = rms(x, w[f"blk.{l}.attn_norm"])
            q = rope(w[f"blk.{l}.attn_q"] @ xb, HEADS, pos)
            k = rope(w[f"blk.{l}.attn_k"] @ xb, KV, pos)
            v = (w[f"blk.{l}.attn_v"] @ xb).reshape(KV, HD)
            caches[l][0].append(k)
            caches[l][1].append(v)
            ks, vs = np.stack(caches[l][0]), np.stack(caches[l][1])
            att = np.zeros((HEADS, HD))
            for h in range(HEADS):
                g = h // (HEADS // KV)
                sc = ks[:, g] @ q[h] / np.sqrt(HD)
                p = np.exp(sc - sc.max())
                p /= p.sum()
                att[h] = p @ vs[:, g]
            x = x + w[f"blk.{l}.attn_output"] @ att.reshape(-1)
            xb = rms(x, w[f"blk.{l}.ffn_norm"])
            gate, up = w[f"blk.{l}.ffn_gate"] @ xb, w[f"blk.{l}.ffn_up"] @ xb
            x = x + w[f"blk.{l}.ffn_down"] @ (gate / (1 + np.exp(-gate)) * up)
        logits.append(out_w @ rms(x, w["output_norm"]))
    return np.array(logits)


PROGRAM = """import std.llama
import std.parallel

fn main():
    model = llama.Model.load("PATH").value_or_panic()
    pool = parallel.Pool.new(3)
    st = llama.State.new(model.cfg, 32)
    toks: [6]i32 = [5, 17, 3, 40, 22, 9]
    for p in 0..6:
        llama.forward(model, st, pool, toks[p], p)
        for i in 0..st.logits.len():
            print(f64(st.logits[i]))
    print(st.len())
    st.truncate(2)
    print(st.len())
"""


def run_model(tmp_path, blob):
    path = tmp_path / "tiny-llama.gguf"
    path.write_bytes(blob)
    res = run_built(PROGRAM.replace("PATH", path.as_posix()), release=True, timeout=120)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.split()
    logits = np.array([float(t) for t in lines[:6 * VOCAB]]).reshape(6, VOCAB)
    return logits, lines[6 * VOCAB:]


@pytest.mark.parametrize("tied, factors", [(False, None), (True, None), (False, [1, 1, 2, 2, 4, 4, 8, 8])])
def test_f32_model_matches_numpy(tmp_path, tied, factors):
    w = make_weights()
    logits, tail = run_model(tmp_path, build_gguf(w, tied=tied, factors=factors))
    want = reference(w, TOKENS, tied=tied, factors=factors)
    np.testing.assert_allclose(logits, want, rtol=2e-3, atol=2e-3)
    assert tail == ["6", "2"]


def test_q8_model_is_close_to_numpy(tmp_path):
    w = make_weights()
    logits, _ = run_model(tmp_path, build_gguf(w, quantized=True))
    want = reference(effective(w, True), TOKENS)
    scale = np.abs(want).max()
    assert np.abs(logits - want).max() < 0.03 * scale
    assert (logits.argmax(1) == want.argmax(1)).mean() >= 0.8


def test_errors_are_reported(tmp_path):
    w = make_weights()
    blob = build_gguf({k: v for k, v in w.items() if k != "blk.1.ffn_up"})
    path = tmp_path / "missing.gguf"
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
    assert "blk.1.ffn_up.weight" in res.stdout


def test_q8_batched_prompt_equals_token_by_token(tmp_path):
    w = make_weights()
    blob = build_gguf(w, quantized=True)
    sequential, _ = run_model(tmp_path, blob)
    path = tmp_path / "tiny-llama.gguf"
    res = run_built("""import std.llama
import std.parallel

fn main():
    model = llama.Model.load("PATH").value_or_panic()
    pool = parallel.Pool.new(3)
    st = llama.State.with_batch(model.cfg, 32, 4)
    a: [4]i32 = [5, 17, 3, 40]
    b: [2]i32 = [22, 9]
    llama.forward_batch(model, st, pool, a, 0)
    llama.forward_batch(model, st, pool, b, 4)
    for i in 0..st.logits.len():
        print(f64(st.logits[i]))
""".replace("PATH", path.as_posix()), release=True, timeout=120)
    assert res.returncode == 0, res.stderr
    np.testing.assert_allclose(np.array([float(t) for t in res.stdout.split()]), sequential[-1], rtol=1e-5, atol=1e-5)
