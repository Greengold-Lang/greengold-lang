"""`gg fuzz`: finds an input that stops the program, shrinks and saves it, replays it.

Spec: 18
"""
import os
import subprocess
import sys

from tests.helpers import ROOT

BUGGY = """fn parse(data: []u8) -> i32:
    if data.len < 2:
        return 0
    if data[0] == 0x80:
        arr: [4]i32 = [0; 4]
        idx = i32(data[1]) % 8
        return arr[idx]
    return 1

fn fuzz_target(data: []u8):
    parse(data)

fn main():
    pass
"""

CLEAN = """fn fuzz_target(data: []u8):
    total = 0
    for b in data:
        total += i32(b)

fn main():
    pass
"""


def gg(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True, cwd=cwd, env=env)


def test_fuzz_finds_shrinks_and_replays(tmp_path):
    (tmp_path / "t.gg").write_text(BUGGY, encoding="utf-8")
    r = gg("fuzz", "t.gg", "--runs", "6000", "--seed", "5", "--max-len", "8", cwd=tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FOUND" in r.stdout
    saved = sorted((tmp_path / "fuzz-crashes").iterdir())
    assert len(saved) == 1
    data = saved[0].read_bytes()
    assert data[0] == 0x80 and len(data) == 2 and data[1] % 8 >= 4          # shrunk to the two bytes that matter
    again = gg("fuzz", "t.gg", "--replay", str(saved[0]), cwd=tmp_path)
    assert again.returncode == 1 and "crashed" in again.stdout


def test_fuzz_of_clean_code_reports_no_findings(tmp_path):
    (tmp_path / "t.gg").write_text(CLEAN, encoding="utf-8")
    r = gg("fuzz", "t.gg", "--runs", "150", "--max-len", "8", "--corpus", "corpus", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "findings 0" in r.stdout
    assert (tmp_path / "corpus").is_dir()


def test_fuzz_needs_a_target(tmp_path):
    (tmp_path / "t.gg").write_text("fn main():\n    pass\n", encoding="utf-8")
    r = gg("fuzz", "t.gg", cwd=tmp_path)
    assert r.returncode == 1 and "fuzz_target" in r.stderr
