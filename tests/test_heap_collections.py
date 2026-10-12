"""List editing (`swap`, `swap_remove`, `remove`, `insert`), heap payloads in Optional, and HashMap with
heap-owning keys and values."""
from pathlib import Path

from tests.helpers import messages, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def _run(name, monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / name).read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    return r.stdout.splitlines()


def test_list_editing(monkeypatch):
    assert _run("list_ops.gg", monkeypatch) == [
        "5 1 2 3 4 0 ", "5 0 2 3 4 ", "0 2 3 4 ", "42 0 7 2 3 4 99 ", "1 5", "a b 2 c z"]


def test_list_editing_is_bounds_checked():
    r = run_built("fn main():\n    xs = List[i32]()\n    xs.push(1)\n    x = xs.remove(3)\n")
    assert r.returncode == 101 and "out of bounds" in r.stderr


def test_hashmap_with_heap_keys_and_values(monkeypatch):
    assert _run("heap_map.gg", monkeypatch) == ["2 5 9", "5", "2 true false 1", "3"]


def test_unwrapping_a_heap_payload_moves_the_optional(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn main():
    l = List[i32]()
    l.push(5)
    o: Optional[List[i32]] = Valid(l)
    xs = o.value_or_panic()
    n: Optional[i32] = Valid(3)
    print(xs.len, n.value_or_panic(), n.value_or(0))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["1", "3", "3"]
    assert "LEAK" not in r.stderr
    moved = src.replace("    n: Optional", "    print(o.has_value())\n    n: Optional")
    assert any("was moved" in m for m in messages(moved))


def test_temporaries_behind_returned_views_are_freed(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn mk(n: i32) -> List[i32]:
    v = List[i32]()
    v.push(n)
    v.push(n + 1)
    return v

fn pick(a: read List[i32], b: read List[i32]) -> ref i32 tied to b:
    return b.get(1)

fn main():
    s = 0
    for i in 0..100:
        s += pick(mk(i), mk(i))
    print(pick(mk(1), mk(2)))
    print(s)
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["3", "5050"]
    assert "LEAK" not in r.stderr
