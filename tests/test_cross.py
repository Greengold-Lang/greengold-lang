"""Cross-compilation: target names, WebAssembly, freestanding ELF, and the object-file fallback."""
import shutil
import subprocess

import pytest

from greengold import targets
from greengold.cli import main

WASM = """extern "env" fn log_i32(x: i32)

fn fib(n: i32) -> i32:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

fn main():
    unsafe:
        log_i32(fib(20))
"""

PLAIN = "static OUT: i64 = 0\n\nfn main():\n    t: i64 = 0\n    for i in 0..10:\n        t += i\n    unsafe:\n        OUT = t\n"


def test_target_names():
    assert targets.triple_of("linux-arm64") == "aarch64-unknown-linux-gnu"
    assert targets.triple_of("wasm32") == "wasm32-unknown-unknown"
    assert targets.triple_of("riscv32-unknown-elf") == "riscv32-unknown-elf"


def test_gg_targets_lists_names(capsys):
    assert main(["targets"]) == 0
    out = capsys.readouterr().out
    assert "linux-arm64" in out and "wasm32" in out and "host:" in out


@pytest.mark.skipif(shutil.which("wasm-ld") is None, reason="wasm-ld is not installed")
def test_webassembly(tmp_path):
    src = tmp_path / "w.gg"
    src.write_text(WASM, encoding="utf-8")
    out = tmp_path / "w.wasm"
    assert main(["build", "--target", "wasm32", str(src), "-o", str(out)]) == 0
    assert out.read_bytes()[:4] == b"\0asm"
    if shutil.which("node"):
        js = tmp_path / "run.js"
        js.write_text("const b=require('fs').readFileSync(process.argv[2]);WebAssembly.instantiate(b,{env:{log_i32:"
                      "x=>console.log(x)}}).then(({instance})=>instance.exports._start());", encoding="utf-8")
        res = subprocess.run(["node", str(js), str(out)], capture_output=True, text=True, timeout=60)
        assert res.stdout.strip() == "6765"


@pytest.mark.skipif(not (shutil.which("clang") and shutil.which("ld.lld")), reason="clang + ld.lld not installed")
@pytest.mark.parametrize("name", ["linux-x64", "linux-arm64", "linux-riscv64"])
def test_freestanding_elf(tmp_path, name):
    if not targets.is_cross(targets.triple_of(name)):
        pytest.skip("not a cross target here")
    src = tmp_path / "l.gg"
    src.write_text(PLAIN, encoding="utf-8")
    out = tmp_path / "l"
    assert main(["build", "--target", name, "--no-std", str(src), "-o", str(out)]) == 0
    assert out.read_bytes()[:4] == b"\x7fELF"


def test_no_linker_writes_the_object(tmp_path, monkeypatch, capsys):
    triple = "aarch64-unknown-linux-gnu"
    if not targets.is_cross(triple):
        pytest.skip("host is aarch64 linux")
    monkeypatch.setattr(targets, "cross_linker", lambda t, free: None)
    src = tmp_path / "l.gg"
    src.write_text("fn main():\n    print(1)\n", encoding="utf-8")
    assert main(["build", "--target", "linux-arm64", str(src), "-o", str(tmp_path / "app")]) == 0
    assert (tmp_path / "app.o").is_file()
    assert "Link it with" in capsys.readouterr().out
