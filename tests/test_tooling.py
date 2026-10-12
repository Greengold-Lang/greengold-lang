"""gg.toml packages, fmt, test, doc, build cache."""
import subprocess
import sys

from greengold.tools import discover_tests, format_source, generate_docs, load_manifest
from tests.helpers import ROOT


def gg(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd or ROOT, timeout=300,
                          env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})


def test_format_source_is_idempotent():
    messy = "fn main():\r\n\tprint(1)   \r\n\r\n\r\n\r\n\r\nfn f():\n    pass"
    once = format_source(messy)
    assert once == "fn main():\n    print(1)\n\n\nfn f():\n    pass\n"
    assert format_source(once) == once


def test_discover_tests():
    assert discover_tests("fn test_a():\n    pass\nfn helper():\n    pass\nfn test_b():\n    pass\n") == ["test_a", "test_b"]


def test_doc_generation():
    md = generate_docs("# Adds.\n# Twice.\nfn add(a: i32) -> i32:\n    return a\n", "m.gg")
    assert "### `fn add(a: i32) -> i32`" in md and "Adds." in md and "Twice." in md


def test_new_build_test_with_dependency(tmp_path):
    assert gg("new", "app", "--path", str(tmp_path / "app")).returncode == 0
    assert gg("new", "mylib", "--path", str(tmp_path / "mylib")).returncode == 0
    (tmp_path / "mylib" / "src" / "util.gg").write_text(
        "public\nfn twice(x: i32) -> i32:\n    return x * 2\n", encoding="utf-8")
    toml = tmp_path / "app" / "gg.toml"
    toml.write_text(toml.read_text().replace('# mylib = { path = "../mylib" }', 'mylib = { path = "../mylib" }'))
    (tmp_path / "app" / "src" / "main.gg").write_text(
        "import mylib.util\n\nfn test_twice():\n    if util.twice(4) != 8:\n        panic(\"bad\")\n\n"
        "fn main():\n    print(util.twice(21))\n", encoding="utf-8")
    m = load_manifest(toml)
    assert "mylib" in m.deps
    r = gg("run", cwd=tmp_path / "app")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "42"
    t = gg("test", "src", cwd=tmp_path / "app")
    assert t.returncode == 0, t.stdout + t.stderr
    assert "test_twice ... ok" in t.stdout
    b1 = gg("build", cwd=tmp_path / "app")
    b2 = gg("build", cwd=tmp_path / "app")
    assert b1.returncode == 0 and b2.returncode == 0, b1.stderr + b2.stderr
    assert "Up to date (cached)" in b2.stdout


def test_failing_test_reports_failure(tmp_path):
    f = tmp_path / "t.gg"
    f.write_text('fn test_bad():\n    panic("boom")\n\nfn main():\n    pass\n', encoding="utf-8")
    t = gg("test", str(f))
    assert t.returncode == 1
    assert "test_bad ... FAILED" in t.stdout


def test_fmt_check_flags_unformatted(tmp_path):
    f = tmp_path / "x.gg"
    f.write_text("fn main():\n    print(1)   \n", encoding="utf-8")
    assert gg("fmt", "--check", str(f)).returncode == 1
    assert gg("fmt", str(f)).returncode == 0
    assert gg("fmt", "--check", str(f)).returncode == 0
