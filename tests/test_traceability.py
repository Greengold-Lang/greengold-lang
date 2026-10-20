"""docs/TRACEABILITY.md is current, and every SPEC section is pinned by a conformance program or a unit-test module.

Spec: 18
"""
import subprocess
import sys

from tests.helpers import ROOT


def test_traceability_matrix_is_current_and_complete():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "traceability.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
