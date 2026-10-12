"""Fetch the LLVM toolchain the playground's Run button uses, and split it for Cloudflare Pages.

The playground compiles in the browser with Ben Smith's WebAssembly builds of clang and lld
(https://github.com/binji/wasm-clang, Apache-2.0; LLVM 8). This script downloads them, checks the SHA-256 of what
was tested, and writes ``website/playground/llvm/`` (git-ignored, about 51 MB: Pages allows 25 MiB per file, so
``clang`` is cut in two). It also writes the wasi-libc files a program links against to
``website/playground/wasi/`` (about 1 MB; those are committed). Run from anywhere:

    python tools/fetch_llvm.py

Without the local copy the page falls back to binji.github.io/wasm-clang, so Run works in development.
"""
from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "website" / "playground"
BASE = "https://binji.github.io/wasm-clang/"
SHA256 = {
    "clang": "2a466f0e990329d3230b869d04fc20803eae96a7feb3a3f6c93e25a77b8aed1d",
    "lld": "36419ed202011765222098d7701218378b67f634d50f0a4625059ae2c9860f48",
    "memfs": "2c72ee42bd9430029dda8c6bafc9f37143f6fe88d5f1ea950a70259ab748bcfe",
    "sysroot.tar": "2435a7b549af30c2be7ec249c405bc2e911ab0c6003012f0909ec3c131bff867",
}
WASI_FILES = {
    "lib/wasm32-wasi/crt1.o": "crt1.o",
    "lib/wasm32-wasi/libc.a": "libc.a",
    "lib/wasm32-wasi/libc.imports": "libc.imports",  # what lld 8 needs to import the WASI calls
    "lib/clang/8.0.1/lib/wasi/libclang_rt.builtins-wasm32.a": "libclang_rt.builtins-wasm32.a",
}
CHUNK = 16 * 1024 * 1024


def fetch(name: str) -> bytes:
    print(f"downloading {name} ...", flush=True)
    with urllib.request.urlopen(BASE + name, timeout=300) as r:
        data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256[name]:
        sys.exit(f"{name}: SHA-256 {digest} is not the tested {SHA256[name]}; refusing to use it.")
    return data


def main() -> None:
    (OUT / "llvm").mkdir(parents=True, exist_ok=True)
    (OUT / "wasi").mkdir(exist_ok=True)
    clang = fetch("clang")
    parts = [clang[i:i + CHUNK] for i in range(0, len(clang), CHUNK)]
    for i, part in enumerate(parts):
        (OUT / "llvm" / f"clang.{i}.wasm").write_bytes(part)
    (OUT / "llvm" / "lld.wasm").write_bytes(fetch("lld"))
    (OUT / "llvm" / "memfs.wasm").write_bytes(fetch("memfs"))
    with tarfile.open(fileobj=io.BytesIO(fetch("sysroot.tar"))) as tar:
        for member, name in WASI_FILES.items():
            (OUT / "wasi" / name).write_bytes(tar.extractfile(member).read())
    print(f"wrote {len(parts)} clang part(s), lld.wasm, memfs.wasm, and the wasi-libc files to {OUT}")


if __name__ == "__main__":
    main()
