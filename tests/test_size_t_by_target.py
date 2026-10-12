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
