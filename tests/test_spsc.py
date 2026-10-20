"""std.heapless.SpscRing: one producer thread and one consumer thread, no locks, no loss, no reordering.

Spec: 16
"""
from tests.helpers import run_gg_source


def test_spsc_single_thread_wraps_and_reports_full(tmp_path):
    r = run_gg_source(tmp_path, """import std.heapless { SpscRing }

fn main():
    r = SpscRing[i32, 4].new(0)
    print(r.push(1), r.push(2), r.push(3), r.push(4), r.len())
    print(r.pop().value_or(-1), r.pop().value_or(-1), r.push(9), r.pop().value_or(-1), r.pop().value_or(-1), r.pop().value_or(-1))
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["true true true false 3", "1 2 true 3 9 -1"]


def test_spsc_two_threads_deliver_every_value_in_order(tmp_path):
    r = run_gg_source(tmp_path, """import std.heapless { SpscRing }
import std.thread { Thread }

fn main():
    ring = Arc[SpscRing[u64, 8]](SpscRing[u64, 8].new(0))
    producer_ring = ring.clone()
    t = Thread.spawn(fn() =>
        produce(producer_ring))
    expected: u64 = 1
    bad = 0
    while expected <= 20000:
        got = ring.value.pop()
        if got.has_value():
            if got.value_or(0) != expected:
                bad += 1
            expected += 1
    t.join()
    print(bad)

fn produce(ring: Arc[SpscRing[u64, 8]]):
    i: u64 = 1
    while i <= 20000:
        if ring.value.push(i):
            i += 1
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["0"]
