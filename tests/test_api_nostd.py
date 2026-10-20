"""`gg api` tells which library modules work with `--no-std`; the claim is checked by compiling each one that says it does.

Spec: 16
"""
import json
import subprocess
import sys

import pytest

from greengold.api import STD, library, no_std_tag
from tests.helpers import ROOT

MODULES = sorted(p.stem for p in STD.glob("*.gg"))


def test_tags_for_known_modules():
    assert no_std_tag("std.bits") == "yes" and no_std_tag("std.heapless") == "yes" and no_std_tag("std.mmio") == "yes"
    assert no_std_tag("std.hash") == "alloc"
    assert no_std_tag("std.fs") == "no" and no_std_tag("std.net") == "no" and no_std_tag("std.thread") == "no"
    assert no_std_tag("core") == "alloc" and no_std_tag("builtin") == "yes"


def test_every_symbol_has_a_tag_in_json_and_text():
    doc = library()
    assert all(s["no_std"] in ("yes", "alloc", "no") for s in doc["symbols"])
    r = subprocess.run([sys.executable, "-m", "greengold", "api"], capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
    assert "# std.bits  [no_std: yes]" in r.stdout and "# std.fs  [no_std: no]" in r.stdout


@pytest.mark.parametrize("module", [m for m in MODULES if no_std_tag(f"std.{m}") != "no"])
def test_modules_tagged_no_std_compile_without_libc(tmp_path, module):
    src = tmp_path / "t.gg"
    allocator = ""
    if no_std_tag(f"std.{module}") == "alloc":      # these use the heap: a bare-metal program names its allocator
        allocator = ("allocator my_alloc, my_resize, my_free\n\nfn my_alloc(size: usize) -> *mut u8:\n    return null\n\n"
                     "fn my_resize(p: *mut u8, size: usize) -> *mut u8:\n    return null\n\nfn my_free(p: *mut u8):\n    pass\n\n")
    src.write_text(f"import std.{module}\n\n{allocator}fn main():\n    pass\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "greengold", "emit-ll", str(src), "--no-std", "--target", "riscv32"],
                       capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    declared = {ln.split('@"')[1].split('"')[0] for ln in r.stdout.splitlines() if ln.startswith("declare") and '@"' in ln}
    assert not (declared & {"malloc", "printf", "fopen", "write", "pthread_create", "getenv"}), declared
