import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_api_reference_is_current():
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "build_api_docs.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
