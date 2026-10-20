import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_learn_reference_is_current():
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "build_learn_reference.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_learn_reference_has_the_core_modules():
    data = json.loads((ROOT / "website" / "learn" / "content" / "stdlib.json").read_text(encoding="utf-8"))
    ids = {m["id"] for m in data["modules"]}
    assert {"builtin", "core", "std.math", "std.string", "std.collections", "std.sort"} <= ids
    math = next(m for m in data["modules"] if m["id"] == "std.math")
    assert any(s["n"] == "sqrt" and "f64" in s["s"] for s in math["symbols"])
