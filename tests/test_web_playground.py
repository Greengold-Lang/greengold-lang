"""The playground entry points (`greengold.web`) must work without the native half of llvmlite,
and the checked-in bundle must contain the current front end."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NO_BINDING = r"""
import sys, json
class Block:
    def find_spec(self, n, p=None, t=None):
        if n.startswith(("llvmlite.binding", "llvmlite.ffi")): raise ImportError(n)
sys.meta_path.insert(0, Block())
from greengold import web
d = json.loads(web.check('fn main():\n    x: i32 = "a"\n'))
assert not d["ok"] and "GG0201" in d["text"], d
assert json.loads(web.check('fn main():\n    print(1)\n'))["ok"]
f = json.loads(web.fix('fn c(a: i32) -> i32:\n    return a\nfn main():\n    y = cc(1)\n', True))
assert "c(1)" in f["source"], f
print("ok")
"""


def test_web_without_llvm_binding():
    r = subprocess.run([sys.executable, "-c", NO_BINDING], capture_output=True, text=True, cwd=ROOT, env={**__import__("os").environ, "GG_WEB_FILE": str(__import__("pathlib").Path(__import__("tempfile").gettempdir()) / "gg_web_test" / "main.gg")})
    assert r.stdout.strip() == "ok", r.stdout + r.stderr


def _lf(data: bytes) -> bytes:
    return data.replace(bytes([13, 10]), bytes([10]))


def test_bundle_is_current():
    with zipfile.ZipFile(ROOT / "website" / "playground" / "gg-bundle.zip") as z:
        names = set(z.namelist())
        for rel in ("greengold/web.py", "greengold/cli.py", "greengold/core/core.gg", "llvmlite/ir/__init__.py"):
            assert rel in names, rel
        for rel in ("greengold/web.py", "greengold/cli.py", "greengold/typecheck.py"):
            assert _lf(z.read(rel)) == _lf((ROOT / rel).read_bytes()), f"{rel} changed: run python tools/build_playground.py"
