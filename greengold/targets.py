"""Targets for `gg build --target`: names, triples, and how to link for another machine.

Code generation works for every target LLVM knows. Linking needs a toolchain for that target:

* the host compiler, when the target is the host;
* `<triple>-gcc` on PATH (a cross compiler with its C library), or `$GG_LINKER` (a whole command);
* `clang --target=<triple>` with `ld.lld`, given a C library through `GG_SYSROOT`, or with no C library
  at all for `--no-std` programs;
* `wasm-ld` for `wasm32-wasi`, linked against a wasi-libc sysroot named by `$GG_WASI_SYSROOT`
  (crt1.o, libc.a, and compiler-rt's builtins): `print`, the heap, and `List` work; the WASI calls are imports;
* `wasm-ld` for `wasm32`, which is always freestanding: the program exports `_start`, and its
  `extern` functions become imports that the host (a browser, a WASI runtime) supplies;
* `zig cc` (from `pip install ziglang`, `$GG_ZIG`, or `zig` on PATH), which carries clang, lld, and the C
  libraries of every target with it: with zig, building needs no system C compiler, and building for
  another machine needs nothing else either.

When no linker is found, `gg build` writes the object file and says how to link it.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

ALIASES: dict[str, str] = {
    "linux-x64": "x86_64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
    "linux-riscv64": "riscv64-unknown-linux-gnu",
    "macos-x64": "x86_64-apple-darwin",
    "macos-arm64": "aarch64-apple-darwin",
    "windows-x64": "x86_64-w64-windows-gnu",
    "windows-arm64": "aarch64-w64-windows-gnu",
    "wasm32": "wasm32-unknown-unknown",
    "wasm32-wasi": "wasm32-unknown-wasi",
    "cortex-m0": "thumbv6m-none-eabi",
    "cortex-m3": "thumbv7m-none-eabi",
    "cortex-m4": "thumbv7em-none-eabihf",
    "cortex-m7": "thumbv7em-none-eabihf",
    "cortex-m33": "thumbv8m.main-none-eabihf",
    "riscv32": "riscv32-unknown-none-elf",
    "riscv64-bare": "riscv64-unknown-none-elf",
    "aarch64-bare": "aarch64-unknown-none",
}


def triple_of(name: str) -> str:
    return ALIASES.get(name, name)


def is_wasm(triple: str) -> bool:
    return triple.startswith("wasm")


def is_wasi(triple: str) -> bool:
    """`wasm32-wasi`: WebAssembly with a C library (wasi-libc), so `print`, the heap, and `List` work."""
    return triple.startswith("wasm") and triple.endswith("wasi")


def wasi_libs() -> list[str]:
    """The files a `wasm32-wasi` program links, from the sysroot in `$GG_WASI_SYSROOT`: crt1.o, libc.a, and the
    compiler-rt builtins. Returns [] when the sysroot is missing."""
    root = os.environ.get("GG_WASI_SYSROOT")
    if not root:
        return []
    base = Path(root)
    found = [base / "lib" / "wasm32-wasi" / "crt1.o", base / "lib" / "wasm32-wasi" / "libc.a"]
    found += sorted(base.glob("lib/clang/*/lib/wasi/libclang_rt.builtins-wasm32.a"))[:1]
    return [str(f) for f in found] if all(f.is_file() for f in found) else []


def _norm(triple: str) -> tuple[str, str]:
    from .codegen_llvm import target_arch, target_os
    return target_arch(triple), target_os(triple)


def is_cross(triple: str) -> bool:
    from .codegen_llvm import native_triple
    return _norm(triple) != _norm(native_triple(None))


def _gcc_names(triple: str) -> list[str]:
    parts = triple.split("-")
    names = [f"{triple}-gcc"]
    if len(parts) == 4 and parts[1] in ("unknown", "pc", "w64"):  # aarch64-unknown-linux-gnu -> aarch64-linux-gnu
        names.append(f"{parts[0]}-{parts[2]}-{parts[3]}-gcc")
    if "windows" in triple:
        names.append(f"{parts[0]}-w64-mingw32-gcc")
    return names


def zig_path() -> str | None:
    """The zig executable: `$GG_ZIG`, the one in the `ziglang` Python package, or `zig` on PATH."""
    custom = os.environ.get("GG_ZIG")
    if custom:
        return custom if Path(custom).is_file() else shutil.which(custom)
    spec = importlib.util.find_spec("ziglang")
    if spec is not None and spec.origin:
        exe = Path(spec.origin).parent / ("zig.exe" if sys.platform == "win32" else "zig")
        if exe.is_file():
            return str(exe)
    return shutil.which("zig")


def zig_target(triple: str) -> str:
    """An LLVM triple as zig names targets: `x86_64-windows-gnu`, `aarch64-macos`, `thumb-freestanding-eabihf`."""
    arch, os_name = _norm(triple)
    if arch.startswith("thumb") or arch.startswith("arm"):
        return f"{'thumb' if arch.startswith('thumb') else 'arm'}-freestanding-eabi" + ("hf" if triple.endswith("hf") else "")
    if os_name == "windows":
        return f"{arch}-windows-gnu"
    if os_name == "macos":
        return f"{arch}-macos"
    if os_name == "linux":
        return f"{arch}-linux-" + ("musl" if "musl" in triple else "gnu")
    return f"{arch}-freestanding"


def zig_linker(triple: str) -> list[str] | None:
    zig = zig_path()
    return [zig, "cc", "-target", zig_target(triple)] if zig else None


def cross_linker(triple: str, freestanding: bool) -> list[str] | None:
    """A command (prefix) that links objects for `triple`, or None."""
    custom = os.environ.get("GG_LINKER")
    if custom == "zig":
        return zig_linker(triple)
    if custom:
        return custom.split()
    if is_wasm(triple):
        wl = shutil.which("wasm-ld")
        if is_wasi(triple) and not wasi_libs():
            return None  # needs a C library to link against
        return [wl] if wl else None
    for name in _gcc_names(triple):
        found = shutil.which(name)
        if found:
            return [found]
    clang = shutil.which("clang")
    sysroot = os.environ.get("GG_SYSROOT")
    if clang and shutil.which("ld.lld") and (freestanding or sysroot):
        cmd = [clang, f"--target={triple}", "-fuse-ld=lld"]
        if sysroot:
            cmd.append(f"--sysroot={sysroot}")
        return cmd
    return zig_linker(triple)


def link_command(cmd: list[str], triple: str, obj: str, out: str, freestanding: bool) -> list[str]:
    if is_wasi(triple):
        libs = wasi_libs()
        return cmd + [libs[0], obj, *libs[1:], "-o", out]
    if is_wasm(triple):
        return cmd + [obj, "-o", out, "--no-entry", "--export=_start", "--allow-undefined"]
    full = cmd + [obj, "-o", out]
    if freestanding:
        full += ["-nostdlib", "-static"]
    elif "windows" not in triple:
        full.append("-lm")
    return full


def how_to_link(triple: str, obj: str) -> str:
    if is_wasi(triple):
        return (f"wasm-ld <sysroot>/lib/wasm32-wasi/crt1.o {obj} <sysroot>/lib/wasm32-wasi/libc.a "
                "<sysroot>/lib/clang/*/lib/wasi/libclang_rt.builtins-wasm32.a -o app.wasm   "
                "(set GG_WASI_SYSROOT to a wasi-libc sysroot and gg links it; the playground ships one)")
    if is_wasm(triple):
        return f"wasm-ld {obj} -o app.wasm --no-entry --export=_start --allow-undefined"
    return f"{_gcc_names(triple)[-1]} {obj} -o app" + ("" if "windows" in triple else " -lm") + \
        "   (or `pip install ziglang`, which links for every target, or set GG_SYSROOT to a C library "         "for this target and install clang + ld.lld)"
