"""std.process: streaming a child's output, feeding its input, and its exit code.

Spec: 16
"""
from tests.helpers import run_gg_source


def test_spawn_read_spawn_write_and_run_with_input(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))
    r = run_gg_source(tmp_path, """import std.process
import std.io

fn main():
    f = process.spawn_read(["python", "-c", "print('a'); print('b'); raise SystemExit(3)"]).value_or_panic()
    print(f.read_line().value_or_panic().value_or("?"))
    print(f.read_rest().value_or_panic().as_str())
    print(f.wait())
    r = process.process_run_input(["python", "-c", "import sys; print(sys.stdin.read().upper())"], "hello").value_or_panic()
    print(r.out.as_str(), r.code)
    w = process.spawn_write(["python", "-c", "import sys; sys.exit(len(sys.stdin.read()))"]).value_or_panic()
    w.write("12345").value_or_panic()
    print(w.wait())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["a", "b", "3", "HELLO", "0", "5"]
