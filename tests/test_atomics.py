"""Hardware atomics: intrinsics with memory orderings, and the lock-free `Atomic[T]`."""
import pytest

from .helpers import HAS_CC, messages, run_built


def test_atomic_intrinsics():
    src = ('fn main():\n    x: i64 = 5\n    unsafe:\n        p = addr_mut(x)\n'
           '        old = atomic_add[i64](p, 3, "acq_rel")\n        print(old, atomic_load[i64](p, "acquire"))\n'
           '        print(atomic_cas[i64](p, 8, 1, "seq_cst"), x)\n        atomic_store[i64](p, 42, "release")\n'
           '        fence("seq_cst")\n        print(atomic_swap[i64](p, 7, "relaxed"), x)\n')
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["5 8", "8 1", "42 7"]


@pytest.mark.parametrize("body, text", [
    ('x: i64 = 1\nprint(atomic_load[i64](addr(x), "seq_cst"))', "unsafe"),
    ('x: i64 = 1\nunsafe:\n    print(atomic_load[i64](addr(x), "release"))', "cannot use the ordering"),
    ('x: i64 = 1\nunsafe:\n    print(atomic_load[i64](addr(x), "fast"))', "memory ordering must be one of"),
    ('x: f64 = 1.0\nunsafe:\n    print(atomic_load[f64](addr(x), "seq_cst"))', "works on integer types"),
])
def test_atomic_misuse(body, text):
    msgs = messages("fn main():\n" + "".join("    " + l + "\n" for l in body.splitlines()))
    assert any(text in m for m in msgs), msgs


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_atomic_counter_under_contention():
    src = """import std.thread { Thread, Atomic }

fn work(h: Arc[Atomic[u64]]):
    for i in 0..10000:
        h.value.fetch_add(1)

fn main():
    hits = Arc[Atomic[u64]](Atomic[u64].new(0))
    ts = List[Thread]()
    for w in 0..4:
        mine = hits.clone()
        ts.push(Thread.spawn(fn() => work(mine)))
    for t in ts:
        t.join()
    print(hits.value.load())
    a = Atomic[i32].new(5)
    print(a.compare_exchange(5, 9), a.compare_exchange(5, 1), a.swap(3), a.load())
"""
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["40000", "true false 9 3"]
