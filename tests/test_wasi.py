"""The `wasm32-wasi` target: C library calls with a 32-bit `size_t`, and the features it does not have."""
import os
import shutil
import subprocess
import sys

import pytest

from greengold import cli
from greengold.codegen_llvm import CodegenError

HEAP = """fn main():
    xs = List[i32]()
    xs.push(4)
    s = string("hi")
    print("heap", xs.len, xs[0], s)
"""


def ir_for(tmp_path, source):
    f = tmp_path / "p.gg"
    f.write_text(source, encoding="utf-8")
    front = cli._frontend([str(f)])
    assert front is not None
    return cli._gen_llvm(front[0], str(f), False, False, "wasm32-wasi", False)


def declaration(ir, name):
    return next(line for line in ir.splitlines() if line.startswith("declare") and f'@"{name}"' in line)


def test_libc_sizes_are_32_bit(tmp_path):
    ir = ir_for(tmp_path, HEAP)
    assert 'target triple = "wasm32-unknown-wasi"' in ir
    assert "i32 %" in declaration(ir, "realloc") and "i64" not in declaration(ir, "realloc")
    assert "i64" not in declaration(ir, "snprintf")


def test_print_and_heap_need_no_freestanding_mode(tmp_path):
    ir_for(tmp_path, HEAP)  # raises CodegenError in the freestanding `wasm32` mode


def test_threads_are_reported(tmp_path):
    with pytest.raises(CodegenError, match="std.thread"):
        ir_for(tmp_path, "import std.thread\n\nfn main():\n    print(1)\n")


def test_other_targets_keep_64_bit_sizes(tmp_path):
    f = tmp_path / "p.gg"
    f.write_text(HEAP, encoding="utf-8")
    front = cli._frontend([str(f)])
    ir = cli._gen_llvm(front[0], str(f), False, False, None, False)
    assert "i64 %" in declaration(ir, "realloc")


@pytest.mark.skipif(not (os.environ.get("GG_WASI_SYSROOT") and shutil.which("wasm-ld") and shutil.which("node")),
                    reason="needs GG_WASI_SYSROOT (a wasi-libc sysroot), wasm-ld, and node")
def test_builds_and_runs(tmp_path):
    src = tmp_path / "p.gg"
    src.write_text(HEAP, encoding="utf-8")
    out = tmp_path / "p.wasm"
    r = subprocess.run([sys.executable, "-m", "greengold", "build", str(src), "--target", "wasm32-wasi", "-o", str(out)],
                       capture_output=True, text=True)
    assert out.is_file(), r.stdout + r.stderr
    js = tmp_path / "run.js"
    js.write_text("const {WASI}=require('node:wasi');const fs=require('fs');(async()=>{"
                  "const w=new WASI({version:'unstable',args:['p'],env:{A:'1'},returnOnExit:true});"
                  "const m=await WebAssembly.compile(fs.readFileSync(process.argv[2]));"
                  "w.start(await WebAssembly.instantiate(m,w.getImportObject()));})();", encoding="utf-8")
    run = subprocess.run(["node", str(js), str(out)], capture_output=True, text=True)
    assert run.stdout.strip() == "heap 1 4 hi", run.stdout + run.stderr
