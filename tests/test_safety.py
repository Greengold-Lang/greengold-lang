"""Stage B: bounds checks remain active in release mode; only `--unchecked` removes them."""
import subprocess
import sys

import pytest

from greengold.cli import compile_to_ir

from .helpers import HAS_CC, ROOT

needs_cc = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

ARRAY_SRC = """\
fn main():
    a = [1, 2, 3]
    i = 5
    print(a[i])
"""

SLICE_SRC = """\
fn get(s: []i32, i: i32) -> i32:
    return s[i]

fn main():
    a = [1, 2, 3]
    print(get(a, 7))
"""

STRING_SRC = """\
fn main():
    s = "abc"
    i = 9
    print(s[i])
"""

CUT_SRC = """\
fn first(s: []i32) -> i32:
    return s[0]

fn main():
    a = [1, 2, 3]
    hi = 9
    print(first(a[0..hi]))
"""

ALL = [ARRAY_SRC, SLICE_SRC, STRING_SRC, CUT_SRC]


@pytest.mark.parametrize("src", ALL)
def test_release_keeps_bounds_checks_in_ir(src):
    ir = compile_to_ir(src, release=True)
    assert "call void @\"gg_rt_panic_bounds\"" in ir or "call void @\"gg_rt_panic" in ir


@pytest.mark.parametrize("src", [ARRAY_SRC, SLICE_SRC, STRING_SRC])
def test_unchecked_removes_bounds_checks_in_ir(src):
    safe = compile_to_ir(src, release=True)
    fast = compile_to_ir(src, release=True, unchecked=True)
    call = "call void @\"gg_rt_panic_bounds\""
    assert safe.count(call) > fast.count(call)
    assert call not in fast


def _run(tmp_path, src, *flags):
    f = tmp_path / "a.gg"
    f.write_text(src, encoding="utf-8")
    cmd = [sys.executable, "-m", "greengold", "run", str(f), *flags]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)


@needs_cc
@pytest.mark.parametrize("src", ALL)
def test_release_traps_out_of_bounds_at_runtime(tmp_path, src):
    r = _run(tmp_path, src, "--release")
    assert r.returncode == 101, (r.stdout, r.stderr)


@needs_cc
def test_debug_also_traps(tmp_path):
    assert _run(tmp_path, ARRAY_SRC).returncode == 101
