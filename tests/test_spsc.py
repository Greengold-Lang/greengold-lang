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


def test_mpmc_ring_single_thread_and_full_empty(tmp_path):
    r = run_gg_source(tmp_path, """import std.heapless { MpmcRing }

fn main():
    q = MpmcRing[i32, 4].new(0)
    print(q.push(1), q.push(2), q.push(3), q.push(4), q.push(5))
    print(q.pop().value_or(-1), q.pop().value_or(-1), q.push(9), q.pop().value_or(-1), q.pop().value_or(-1), q.pop().value_or(-1), q.pop().value_or(-1))
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["true true true true false", "1 2 true 3 4 9 -1"]


def test_mpmc_ring_many_producers_and_consumers_lose_nothing(tmp_path):
    r = run_gg_source(tmp_path, """import std.heapless { MpmcRing }
import std.thread { Thread, Atomic }

fn produce(q: Arc[MpmcRing[u64, 16]], base: u64):
    i: u64 = 1
    while i <= 5000:
        if q.value.push(base + i):
            i += 1

fn drain(q: Arc[MpmcRing[u64, 16]], total: Arc[Atomic[u64]], count: Arc[Atomic[u64]]):
    while count.value.load() < 20000:
        got = q.value.pop()
        if got.has_value():
            total.value.fetch_add(got.value_or(0))
            count.value.fetch_add(1)

fn main():
    q = Arc[MpmcRing[u64, 16]](MpmcRing[u64, 16].new(0))
    total = Arc[Atomic[u64]](Atomic[u64].new(0))
    count = Arc[Atomic[u64]](Atomic[u64].new(0))
    workers = List[Thread]()
    for p in 0..4:
        qq = q.clone()
        base = u64(p) * 1000000
        workers.push(Thread.spawn(fn() =>
            produce(qq, base)))
    for _c in 0..3:
        qq = q.clone()
        tt = total.clone()
        cc = count.clone()
        workers.push(Thread.spawn(fn() =>
            drain(qq, tt, cc)))
    for i in 0..workers.len:
        workers[i].join()
    print(count.value.load(), total.value.load())
""")
    assert r.returncode == 0, r.stderr
    want = sum(base + i for base in (0, 1000000, 2000000, 3000000) for i in range(1, 5001))
    assert r.stdout.split() == ["20000", str(want)]
