"""An LLVM outside the compiler: `clang` (or `zig cc`) turns the IR text into object code.

The LLVM inside llvmlite is fixed by the llvmlite release. Running a separate LLVM lets the user pick the
version: `GG_LLVM` names the program (`clang`, a path to one, or `zig` for the clang inside Zig), otherwise
`clang` on PATH is used. `GG_BACKEND=clang` makes the compiler use it, `GG_BACKEND=llvmlite` keeps the built-in
one; without `GG_BACKEND`, llvmlite is used when it is installed and this LLVM otherwise.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

MIN_VERSION = 15  # the first LLVM that reads opaque pointers (`ptr`), which newer llvmlite writes


class ToolError(Exception):
    pass


@lru_cache(maxsize=None)
def find() -> tuple[tuple[str, ...], int] | None:
    """The command that runs clang (e.g. `("clang",)` or `("zig", "cc")`) and its LLVM major version."""
    want = os.environ.get("GG_LLVM", "").strip()
    candidates: list[tuple[str, ...]] = []
    if want:
        path = shutil.which(want) or (want if Path(want).is_file() else None)
        if path is None:
            return None
        candidates.append((path, "cc") if Path(path).stem.lower() == "zig" else (path,))
    else:
        clang = shutil.which("clang")
        if clang:
            candidates.append((clang,))
    for cmd in candidates:
        try:
            out = subprocess.run([*cmd, "--version"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"clang version (\d+)", out)
        if m and int(m.group(1)) >= MIN_VERSION:
            return cmd, int(m.group(1))
    return None


def describe() -> str:
    found = find()
    if found is None:
        return "not found"
    cmd, major = found
    return f"{' '.join(cmd)} (LLVM {major})"


def _run(ir_text: str, triple: str, release: bool, flags: list[str], suffix: str) -> bytes:
    found = find()
    if found is None:
        raise ToolError(f"no LLVM found: install clang {MIN_VERSION} or newer, or set GG_LLVM to one")
    cmd, _ = found
    with tempfile.TemporaryDirectory(prefix="greengold_llvm_") as tmp:
        src, out = Path(tmp) / "program.ll", Path(tmp) / f"program{suffix}"
        src.write_text(ir_text, encoding="utf-8")
        args = [*cmd, "-target", triple, "-O3" if release else "-O0", "-Wno-override-module",
                *flags, "-x", "ir", str(src), "-o", str(out)]
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode != 0:
            raise ToolError(f"generated LLVM IR is invalid (compiler error):\n{res.stderr.strip()}")
        return out.read_bytes()


def object_code(ir_text: str, triple: str, release: bool) -> bytes:
    return _run(ir_text, triple, release, ["-c"], ".o")


def bitcode(ir_text: str, triple: str, release: bool) -> bytes:
    return _run(ir_text, triple, release, ["-c", "-emit-llvm"], ".bc")


def optimized_ir(ir_text: str, triple: str, release: bool) -> str:
    return _run(ir_text, triple, release, ["-S", "-emit-llvm"], ".ll").decode("utf-8")


@lru_cache(maxsize=None)
def data_layout(triple: str) -> str | None:
    """The data layout this LLVM uses for `triple`, read from the IR it writes for an empty C file."""
    found = find()
    if found is None:
        return None
    cmd, _ = found
    res = subprocess.run([*cmd, "-target", triple, "-S", "-emit-llvm", "-x", "c", "-", "-o", "-"],
                         input="", capture_output=True, text=True)
    m = re.search(r'^target datalayout = "([^"]*)"', res.stdout, re.M)
    return m.group(1) if m else None


@lru_cache(maxsize=None)
def has_target(triple: str) -> bool:
    """Whether this LLVM can write code for `triple`."""
    found = find()
    if found is None:
        return False
    cmd, _ = found
    res = subprocess.run([*cmd, "-target", triple, "-S", "-emit-llvm", "-x", "c", "-", "-o", os.devnull],
                         input="", capture_output=True, text=True)
    return res.returncode == 0
