"""standard library modules (sort, collections, string, math, rand, time, process, fs)."""
import subprocess
import sys

import pytest

from tests.helpers import HAS_CC, ROOT, run_example, run_gg_source


def test_strings_std_output():
    r = run_example("strings_std.gg")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "hello, world 12"
    assert lines[3] == "-1234 -1 18446744073709551615"
    assert lines[4] == "-9223372036854775808 7"
    assert lines[6] == "n=-42 u=0 f=2.5 b=true"
    assert lines[9] == "a::b::c ababab"


def test_stdlib_misc_exit_code():
    r = run_example("stdlib_misc.gg")
    assert r.returncode == 3, r.stderr
    assert r.stdout.splitlines()[:3] == ["4 81 6 5 10", "2 3 1024", "true true true"]
    assert r.stdout.splitlines()[-1] == "unset ok"


def test_fs_roundtrip():
    r = run_example("fs_std.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["true true false", "3 line2", "true true"]


def test_substr_out_of_range_panics(tmp_path):
    r = run_gg_source(tmp_path, 'import std.string\n\nfn main():\n    print(string.substr("abc", 2, 9))\n')
    assert r.returncode != 0
    assert "substr: range out of bounds" in r.stderr


