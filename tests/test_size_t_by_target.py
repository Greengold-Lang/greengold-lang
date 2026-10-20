"""`size_t` follows the target's pointer width. A prefix test on "arm" once matched `arm64-apple-darwin` (Apple
Silicon macOS), made `snprintf` take a 32-bit size, and broke every program that prints a runtime error there.
These tests build the IR for that triple on any host, so the mistake shows up everywhere, not only on a Mac."""
from pathlib import Path

import pytest

from greengold import cli
from greengold.codegen_llvm import is_32bit_triple

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("triple", [
    "arm64-apple-darwin", "arm64-apple-darwin25.0.0", "arm64e-apple-darwin", "aarch64-unknown-linux-gnu",
    "aarch64-apple-darwin", "x86_64-unknown-linux-gnu", "x86_64-w64-windows-gnu", "riscv64-unknown-linux-gnu",
])
def test_64_bit_targets(triple):
    assert not is_32bit_triple(triple)


@pytest.mark.parametrize("triple", [
    "wasm32-unknown-wasi", "wasm32-unknown-unknown", "thumbv7em-none-eabihf", "armv7-unknown-linux-gnueabihf",
    "arm-unknown-linux-gnueabi", "i686-pc-linux-gnu", "i386-unknown-linux-gnu", "riscv32-unknown-elf",
])
def test_32_bit_targets(triple):
    assert is_32bit_triple(triple)


@pytest.mark.parametrize("target", ["arm64-apple-darwin", "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"])
def test_ir_for_64_bit_targets_uses_64_bit_sizes(target):
    """The standard library declares `snprintf(.., n: usize, ..)`; the runtime-error code calls it too. They must agree."""
    front = cli._frontend([str(ROOT / "examples" / "strings_std.gg")])
    assert front is not None
    ir = cli._gen_llvm(front[0], front[1], False, False, target, False)
    line = next(ln for ln in ir.splitlines() if ln.startswith("declare") and '@"snprintf"' in ln)
    assert "i64 %" in line and "i32 %\".2\"" not in line, line


FFI32 = """extern "string.h" fn memcmp(a: *u8, b: *u8, n: usize) -> i32
extern "string.h" fn strlen(s: *u8) -> usize
extern "stdlib.h" fn malloc(n: usize) -> *mut u8

fn main():
    unsafe:
        p = malloc(16)
        q = malloc(16)
        n = memcmp(p, q, 8)
        m = strlen(p)
"""


@pytest.mark.parametrize("target", ["riscv32", "thumbv7em-none-eabihf", "i686-unknown-linux-gnu"])
def test_c_functions_take_a_32_bit_size_t_on_32_bit_targets(tmp_path, target):
    """`usize` is 64 bits inside Greengold; the C function must still be called with a 32-bit `size_t`
    (on a 32-bit ABI an `i64` argument takes two registers, so every argument after it moves)."""
    src = tmp_path / "f.gg"
    src.write_text(FFI32, encoding="utf-8")
    front = cli._frontend([str(src)])
    assert front is not None
    text = cli._gen_llvm(front[0], front[1], False, False, target, "linux" not in target)
    for sym in ("malloc", "memcmp", "strlen"):
        line = next(ln for ln in text.splitlines() if (ln.startswith("declare") or ln.startswith("define weak")) and f'@"{sym}"(' in ln)
        assert "i64" not in line, line
    if "linux" not in target:      # freestanding: the library functions Greengold provides itself have the C signature too
        mem = next(ln for ln in text.splitlines() if ln.startswith("define weak") and '@"memcpy"(' in ln)
        assert "i64" not in mem, mem


def test_c_functions_keep_a_64_bit_size_t_on_64_bit_targets(tmp_path):
    src = tmp_path / "f.gg"
    src.write_text(FFI32, encoding="utf-8")
    front = cli._frontend([str(src)])
    text = cli._gen_llvm(front[0], front[1], False, False, "x86_64-unknown-linux-gnu", False)
    line = next(ln for ln in text.splitlines() if ln.startswith("declare") and '@"malloc"(' in ln)
    assert "i64" in line
