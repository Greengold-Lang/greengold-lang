"""std.tokenizer against SentencePiece and Hugging Face tokenizers."""
import json

import pytest

from .gguf_writer import (kv_f32_array, kv_i32_array, kv_str, kv_str_array, kv_u32, write_gguf)
from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

CORPUS = [
    "Hello, world! This is a small test of the tokenizer.",
    "The quick brown fox jumps over the lazy dog 12345 times.",
    "def add(a, b):\n    return a + b\n\nprint(add(2, 3))",
    "I'm sure we'll see what they've done; it's 100% fine.",
    "Café au lait costs 3.50 euros, naïve résumé.",
    "   leading spaces and  double  spaces   ",
    "tokens tokens tokenization tokenizer tokenize",
    "line one\nline two\r\nline three\n\n\nend",
] * 6

TEXTS = [
    "Hello, world!",
    "The quick brown fox",
    "I'm sure it's fine; they've done 123456 things.",
    "def f(x):\n    return x\n\n\nend  ",
    "Café naïve",
    "  two  spaces   ",
    "zzz qqq xyzzy",
    "tokenization of tokens",
    "",
    "a",
    " leading",
    "emoji \U0001F600 and 中文",
]


def run_encoder(tmp_path, gguf_bytes, texts, special=False):
    model = tmp_path / "tok.gguf"
    model.write_bytes(gguf_bytes)
    data = tmp_path / "texts.bin"
    data.write_bytes(b"\x01".join(t.encode() for t in texts))
    src = f"""import std.gguf
import std.tokenizer
import std.fs

fn main():
    g = gguf.Gguf.open("{model.as_posix()}").value_or_panic()
    tok = tokenizer.Tokenizer.from_gguf(g).value_or_panic()
    text = fs.read_file_to_string("{data.as_posix()}").value_or_panic()
    bytes = text.as_str()
    start: usize = 0
    for i in 0..bytes.len + 1:
        if i == bytes.len or bytes[i] == 1:
            ids = tok.encode(bytes[start..i], false, {"true" if special else "false"})
            line = string.new()
            for k in 0..ids.len():
                line.append_i64(i64(ids[k]))
                line.append_byte(32)
            print(line.as_str())
            back = tok.decode(ids[..])
            hex = string.new()
            for k in 0..back.len():
                hex.append_str("0123456789abcdef"[usize(back.as_str()[k] >> 4)..usize(back.as_str()[k] >> 4) + 1])
                hex.append_str("0123456789abcdef"[usize(back.as_str()[k] & 15)..usize(back.as_str()[k] & 15) + 1])
            print(hex.as_str())
            start = i + 1
"""
    res = run_built(src, release=True, timeout=120)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.split("\n")
    out = []
    for n in range(len(texts)):
        ids = [int(t) for t in lines[2 * n].split()]
        out.append((ids, bytes.fromhex(lines[2 * n + 1]).decode(errors="replace")))
    return out


def train_spm(d):
    """Trains a small SentencePiece BPE model; returns (processor, GGUF key/value entries of its tokenizer)."""
    spm = pytest.importorskip("sentencepiece")
    from sentencepiece import sentencepiece_model_pb2 as pb
    corpus = d / "corpus.txt"
    corpus.write_text(chr(10).join(CORPUS), encoding="utf-8")
    spm.SentencePieceTrainer.train(
        input=str(corpus), model_prefix=str(d / "m"), vocab_size=330, model_type="bpe", byte_fallback=True,
        add_dummy_prefix=True, remove_extra_whitespaces=False, normalization_rule_name="identity",
        user_defined_symbols=["<|sp|>"], unk_id=0, bos_id=1, eos_id=2, pad_id=-1, hard_vocab_limit=False)
    proto = pb.ModelProto()
    proto.ParseFromString((d / "m.model").read_bytes())
    pieces = [(p.piece, p.score, p.type) for p in proto.pieces]
    kvs = [kv_str("tokenizer.ggml.model", "llama"),
           kv_str_array("tokenizer.ggml.tokens", [p[0] for p in pieces]),
           kv_f32_array("tokenizer.ggml.scores", [p[1] for p in pieces]),
           kv_i32_array("tokenizer.ggml.token_type", [p[2] for p in pieces]),
           kv_u32("tokenizer.ggml.bos_token_id", 1), kv_u32("tokenizer.ggml.eos_token_id", 2),
           kv_u32("tokenizer.ggml.unknown_token_id", 0)]
    return spm.SentencePieceProcessor(model_file=str(d / "m.model")), kvs, pieces


@pytest.fixture(scope="module")
def spm_model(tmp_path_factory):
    sp, kvs, _ = train_spm(tmp_path_factory.mktemp("spm"))
    return sp, write_gguf([kv_str("general.architecture", "llama"), *kvs], [])


def test_sentencepiece_matches_reference(tmp_path, spm_model):
    sp, blob = spm_model
    got = run_encoder(tmp_path, blob, TEXTS)
    for text, (ids, back) in zip(TEXTS, got):
        assert ids == sp.encode(text), text
        assert back == sp.decode(sp.encode(text)) or back == " " + sp.decode(sp.encode(text)) or text == "", (text, back)


def test_sentencepiece_special_tokens(tmp_path, spm_model):
    sp, blob = spm_model
    special = sp.piece_to_id("<|sp|>")
    (ids_a, _), (ids_b, _) = run_encoder(tmp_path, blob, ["a<|sp|>", "a"], special=True)
    assert ids_a == ids_b + [special]
    (plain, _), = run_encoder(tmp_path, blob, ["a<|sp|>"], special=False)
    assert special not in plain


LLAMA3 = (r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+"
          r"|\s+(?!\S)|\s+")


@pytest.fixture(scope="module")
def bpe_model(tmp_path_factory):
    tokenizers = pytest.importorskip("tokenizers")
    from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers, trainers
    tk = Tokenizer(models.BPE())
    tk.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(LLAMA3), behavior="isolated", invert=False),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
    tk.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(vocab_size=420, initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
                                  special_tokens=["<|begin_of_text|>", "<|end_of_text|>"], show_progress=False)
    tk.train_from_iterator(CORPUS, trainer)
    spec = json.loads(tk.to_str())
    vocab = spec["model"]["vocab"]
    tokens = [t for t, _ in sorted(vocab.items(), key=lambda kv: kv[1])]
    merges = [m if isinstance(m, str) else " ".join(m) for m in spec["model"]["merges"]]
    types = [3 if t.startswith("<|") else 1 for t in tokens]
    kvs = [kv_str("general.architecture", "llama"), kv_str("tokenizer.ggml.model", "gpt2"),
           kv_str_array("tokenizer.ggml.tokens", tokens), kv_i32_array("tokenizer.ggml.token_type", types),
           kv_str_array("tokenizer.ggml.merges", merges), kv_u32("tokenizer.ggml.bos_token_id", 0),
           kv_u32("tokenizer.ggml.eos_token_id", 1)]
    return tk, write_gguf(kvs, [])


def test_byte_level_bpe_matches_reference(tmp_path, bpe_model):
    tk, blob = bpe_model
    texts = [t for t in TEXTS if "\U0001F600" not in t and "中" not in t]
    got = run_encoder(tmp_path, blob, texts)
    for text, (ids, back) in zip(texts, got):
        assert ids == tk.encode(text).ids, text
        assert back == text, (text, back)


def test_byte_level_bpe_non_ascii_round_trips(tmp_path, bpe_model):
    _, blob = bpe_model
    texts = ["emoji \U0001F600 and 中文", "éè ü"]
    for text, (ids, back) in zip(texts, run_encoder(tmp_path, blob, texts)):
        assert back == text and len(ids) > 0
