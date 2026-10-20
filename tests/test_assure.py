"""gg sbom, gg unsafe-audit, gg repro.

Spec: 18
"""
import json
import os
import subprocess
import sys

from tests.helpers import ROOT

PROGRAM = """static counter: u32 = 0

@section(".isr_vector")
@used
static vectors: [2]u32 = [1, 2]

@interrupt
fn Tick():
    unsafe:
        counter = counter + 1

fn main():
    Tick()
    unsafe:
        print(counter, vectors[1])
"""


def gg(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True, cwd=cwd, env=env)


def test_sbom_lists_sources_library_and_tools(tmp_path):
    (tmp_path / "app.gg").write_text("import std.bits\n\nfn main():\n    print(bits.popcount(u8(7)))\n", encoding="utf-8")
    r = gg("sbom", "app.gg", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["bomFormat"] == "CycloneDX" and doc["specVersion"] == "1.5"
    names = {c["name"] for c in doc["components"]}
    assert {"greengold", "app.gg", "std.bits", "llvmlite"} <= names | {doc["metadata"]["tools"]["components"][0]["name"]}
    file_c = next(c for c in doc["components"] if c["name"] == "app.gg")
    assert len(file_c["hashes"][0]["content"]) == 64
    again = gg("sbom", "app.gg", cwd=tmp_path)
    assert again.stdout == r.stdout                     # no time or machine in it
    spdx = json.loads(gg("sbom", "app.gg", "--format", "spdx", cwd=tmp_path).stdout)
    assert spdx["spdxVersion"] == "SPDX-2.3" and any(f["fileName"] == "app.gg" for f in spdx["files"])


def test_unsafe_audit_lists_each_use(tmp_path):
    (tmp_path / "a.gg").write_text(PROGRAM, encoding="utf-8")
    r = gg("unsafe-audit", "a.gg", "--json", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)["unsafe_uses"]
    kinds = sorted(x["kind"] for x in rows)
    assert kinds.count("unsafe-block") == 2 and kinds.count("static") == 2 and kinds.count("attribute") >= 3
    assert all(x["file"] and x["file"].endswith("a.gg") for x in rows)


def test_repro_confirms_identical_builds(tmp_path):
    (tmp_path / "a.gg").write_text("fn main():\n    print(6 * 7)\n", encoding="utf-8")
    r = gg("repro", "a.gg", "--release", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("reproducible:")
