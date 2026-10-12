"""`test` blocks beside functions, and `gg test --json`."""
import json
import subprocess
import sys

from greengold.fmt import format_source
from greengold.tools import collect_cases
from tests.helpers import ROOT


def gg(*args):
    return subprocess.run(
        [sys.executable, "-m", "greengold", *args],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
    )


def test_blocks_are_named_after_the_function_above():
    src = (
        "fn add(a: i32, b: i32) -> i32:\n    return a + b\n\n"
        "test:\n    require add(2, 3) == 5\n\n"
        "test:\n    require add(0, 0) == 0\n\n"
        "test negatives:\n    require add(-1, 1) == 0\n\n"
        "fn test_zero():\n    require add(0, 1) == 1\n"
    )
    found = [(c.name, c.kind, c.callable) for c in collect_cases(src)]
    assert found == [
        ("add.test", "block", "gg_test_1"),
        ("add.test.2", "block", "gg_test_2"),
        ("add.negatives", "block", "gg_test_3"),
        ("test_zero", "function", "test_zero"),
    ]


def test_a_block_before_any_function_is_named_test():
    found = collect_cases("test:\n    require true\n")
    assert [(c.name, c.kind) for c in found] == [("test", "block")]


def test_format_keeps_a_test_block():
    src = (
        "fn add(a: i32, b: i32) -> i32:\n"
        "    return a + b\n"
        "\n"
        "test:\n"
        "    require add(2, 3) == 5\n"
        "\n"
        "fn main():\n"
        "    print(1)\n"
    )
    assert format_source(src) == src


def test_run_does_not_call_a_test_block(tmp_path):
    path = tmp_path / "m.gg"
    path.write_text(
        "fn main():\n    print(1)\n\ntest:\n    require false\n",
        encoding="utf-8",
    )
    ran = gg("run", str(path))
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "1"
    tested = gg("test", str(path))
    assert tested.returncode == 1
    assert "main.test ... FAILED" in tested.stdout


def test_json_report_counts_blocks_and_functions(tmp_path):
    path = tmp_path / "m.gg"
    path.write_text(
        "fn add(a: i32, b: i32) -> i32:\n    return a + b\n\n"
        "test:\n    require add(2, 3) == 5\n\n"
        "test bad:\n    require add(2, 3) == 4\n\n"
        "fn test_ok():\n    require add(1, 1) == 2\n\n"
        "fn main():\n    print(add(2, 3))\n",
        encoding="utf-8",
    )
    result = gg("test", "--json", str(path))
    assert result.returncode == 1
    doc = json.loads(result.stdout)
    assert doc["schema_version"] == 1
    assert doc["tool"]["name"] == "gg"
    assert doc["command"] == "test"
    assert doc["ok"] is False
    assert doc["summary"] == {"passed": 2, "failed": 1}
    rows = {(t["name"], t["kind"], t["status"]) for t in doc["tests"]}
    assert rows == {
        ("add.test", "block", "passed"),
        ("add.bad", "block", "failed"),
        ("test_ok", "function", "passed"),
    }
    failed = next(t for t in doc["tests"] if t["status"] == "failed")
    assert set(failed) == {"name", "file", "line", "kind", "status", "message"}
    assert failed["line"] >= 1
    assert "require condition failed" in failed["message"]
    assert "add(2, 3) == 4 (left: 5, right: 4)" in failed["message"]
    assert failed["file"].endswith("m.gg")
