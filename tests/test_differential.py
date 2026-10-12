"""Debug and release outputs must be identical in all cleanly running examples."""
import subprocess
import sys

import pytest

from .helpers import HAS_CC, ROOT, EXAMPLES_DIR

SKIP = {"bounds_fail.gg", "value_or_panic_fail.gg", "extern_math.gg"}
EXAMPLES = sorted(p for p in (EXAMPLES_DIR).glob("*.gg") if p.name not in SKIP)


def _run(path, *flags):
    cmd = [sys.executable, "-m", "greengold", "run", str(path), *flags]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, input="", timeout=180)


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_debug_and_release_agree(path):
    d = _run(path)
    r = _run(path, "--release")
    assert (d.returncode, d.stdout) == (r.returncode, r.stdout)
