"""apps/gg-infer: the whole path (GGUF, tokenizer, model, sampler) against numpy and SentencePiece."""
import subprocess
import sys

import numpy as np
import pytest

from .helpers import HAS_CC, ROOT
from .test_llama import TOKENS, build_gguf, make_weights, reference
from .test_tokenizer import train_spm

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")


def piece_bytes(piece: str, kind: int) -> bytes:
    if kind == 6:  # <0xXX>
        return bytes([int(piece[3:5], 16)])
    if kind == 3:
        return b""
    return piece.replace("▁", " ").encode()


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    d = tmp_path_factory.mktemp("infer")
    sp, kvs, pieces = train_spm(d)
    w = make_weights(seed=11, vocab=len(pieces))
    path = d / "tiny.gguf"
    path.write_bytes(build_gguf(w, extra_kvs=kvs))
    return path, sp, pieces, w


def run_cli(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "greengold", "run", "apps/gg-infer/main.gg", "--release", "--", *args]
    return subprocess.run(cmd, capture_output=True, cwd=ROOT, timeout=300, env={"PYTHONPATH": str(ROOT), **__import__("os").environ})


def test_greedy_generation_matches_numpy(tiny):
    path, sp, pieces, w = tiny
    prompt = "Hello world"
    seq = [sp.bos_id()] + sp.encode(prompt)
    out = prompt.encode()
    for _ in range(10):
        nxt = int(np.argmax(reference(w, seq)[-1]))
        if nxt == sp.eos_id():
            break
        out += piece_bytes(pieces[nxt][0], pieces[nxt][2])
        seq.append(nxt)
    res = run_cli(str(path), "-p", prompt, "-n", "10", "--temp", "0", "-t", "2")
    assert res.returncode == 0, res.stderr.decode(errors="replace")
    assert res.stdout.replace(b"\r\n", b"\n") == out + b"\n"  # Windows writes "\n" as "\r\n"
    err = res.stderr.decode()
    assert "prompt:" in err and "tokens/s" in err


def test_sampling_is_repeatable_and_info(tiny):
    path, *_ = tiny
    a = run_cli(str(path), "-p", "a b", "-n", "8", "--seed", "5", "-t", "1")
    b = run_cli(str(path), "-p", "a b", "-n", "8", "--seed", "5", "-t", "3")
    assert a.returncode == 0 and a.stdout == b.stdout and len(a.stdout) > 4
    info = run_cli(str(path), "--info")
    assert info.returncode == 0
    text = info.stdout.decode()
    assert "layers" in text and "vocabulary" in text


def test_cli_reports_bad_input(tiny, tmp_path):
    path, *_ = tiny
    assert run_cli().returncode == 2
    missing = run_cli(str(tmp_path / "nothing.gguf"))
    assert missing.returncode == 1 and b"error" in missing.stderr
    bad = run_cli(str(path), "--bogus", "1")
    assert bad.returncode == 2
