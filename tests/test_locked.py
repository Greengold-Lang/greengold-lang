"""`std.thread.Locked[T]`: a value behind its own mutex, changed through a `Guard`."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_locked_counter_and_list_across_threads(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "locked.gg").read_text(encoding="utf-8"), timeout=60)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["4000 4", "4000 99"]


def _codes(src, tmp_path=None):
    if "import " not in src:
        return [d.message for d in front_end(src)[1]]
    from greengold.cli import analyze
    f = tmp_path / "main.gg"
    f.write_text(src, encoding="utf-8")
    return [d.message for d in analyze([str(f)])[2].items]


def test_guard_cannot_outlive_or_leave(tmp_path):
    src = """\
import std.thread

fn leak() -> thread.Guard[i64]:
    m = thread.Locked[i64].new(1)
    return m.lock()

fn main():
    m = thread.Locked[i64].new(1)
    g = m.lock()
    n = m
    g.value() += 1
"""
    msgs = _codes(src, tmp_path)
    assert any("destroyed upon returning" in m for m in msgs)
    assert any("still tied to it" in m for m in msgs)


def test_guard_cannot_go_to_another_thread(tmp_path):
    src = """\
import std.thread

fn use(g: thread.Guard[i64]):
    pass

fn main():
    m = thread.Locked[i64].new(1)
    g = m.lock()
    t = thread.Thread.spawn(fn() => use(g))
"""
    assert any("reference field" in m for m in _codes(src, tmp_path))


def test_struct_with_reference_field_from_a_call_is_tied():
    src = """\
struct P:
    hp: i32

struct View:
    who: read P tied to self

fn look(p: read P) -> View:
    return View{ who: p }

fn leak() -> View:
    p = P{ hp: 1 }
    return look(p)

fn main():
    pass
"""
    assert any("destroyed upon returning" in m for m in _codes(src))


def test_assigning_to_a_call_needs_lend():
    src = "fn f() -> i32:\n    return 1\n\nfn main():\n    f() = 2\n"
    assert any("is a value, not a place" in m for m in _codes(src))
