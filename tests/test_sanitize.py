"""Runs generated C with ASan/UBSan across all examples (with GG_SANITIZE=1, on supported platforms)."""
import os
import subprocess
import sys

import pytest

from .helpers import HAS_CC, ROOT

SKIP_EXAMPLES = {"bounds_fail.gg", "value_or_panic_fail.gg", "extern_math.gg"}  # deliberately failing / external dependency
EXAMPLES = sorted(p for p in (ROOT / "examples").glob("*.gg") if p.name not in SKIP_EXAMPLES)


def _sanitizer_works(tmp_path) -> bool:
    import shutil
    cc = shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        return False
    src = tmp_path / "t.c"
    src.write_text("int main(void){return 0;}", encoding="utf-8")
    r = subprocess.run([cc, "-fsanitize=address,undefined", str(src), "-o", str(tmp_path / "t")],
                       capture_output=True)
    return r.returncode == 0


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
@pytest.mark.parametrize("release", [False, True], ids=["debug", "release"])
def test_examples_clean_under_sanitizers(tmp_path, path, release):
    if not _sanitizer_works(tmp_path):
        pytest.skip("sanitizer not supported")
    cmd = [sys.executable, "-m", "greengold", "run", str(path)] + (["--release"] if release else [])
    env = dict(os.environ, GG_SANITIZE="1")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env,
                       input="", timeout=180)
    assert "runtime error" not in r.stderr and "AddressSanitizer" not in r.stderr, r.stderr
