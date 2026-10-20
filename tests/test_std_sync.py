"""std.thread additions: try_lock, timed waits, Semaphore, Barrier, RwLock, Once, ThreadLocal, Channel[T]."""
from tests.helpers import run_gg_source

PROGRAM = r'''import std.thread { Thread, Mutex, Cond, Semaphore, Barrier, RwLock, Once, ThreadLocal, Channel, Atomic }

fn hello():
    print("once")

fn main():
    m = Mutex.new()
    print(m.try_lock(), m.try_lock())
    m.unlock()
    s = Semaphore.new(2)
    print(s.try_acquire(), s.try_acquire(), s.try_acquire(), s.acquire_timeout(30))
    s.release()
    print(s.available())
    ch = Arc[Channel[string]](Channel[string].new(2))
    mine = ch.clone()
    t = Thread.spawn(fn() => produce(mine))
    got = 0
    while true:
        v = ch.value.recv()
        if v.is_none():
            break
        print(v.value_or_panic())
        got += 1
    t.join()
    print(got, ch.value.recv_timeout(20).is_none())
    o = Once.new()
    print(o.run(hello), o.run(hello), o.is_done())
    rw = RwLock.new()
    if true:
        r1 = rw.read_lock()
        r2 = rw.read_lock()
        print(rw.readers(), rw.can_read())
    w = rw.write_lock()
    print(rw.readers())
    tl = ThreadLocal.new(7)
    tl.set(9)
    print(tl.get())
    b = Arc[Barrier](Barrier.new(3))
    cnt = Arc[Atomic[i64]](Atomic[i64].new(0))
    ts = List[Thread]()
    for i in 0..3:
        bb = b.clone()
        cc = cnt.clone()
        ts.push(Thread.spawn(fn() => work(bb, cc)))
    for x in ts:
        x.join()
    print(cnt.value.load())
    u = Channel[i64].unbounded()
    u.send(1)
    u.send(2)
    print(u.len(), u.try_recv().value_or(0), u.try_recv().value_or(0), u.try_recv().is_none())

fn produce(c: Arc[Channel[string]]):
    c.value.send("a")
    c.value.send("b")
    c.value.send("c")
    c.value.close()

fn work(b: Arc[Barrier], c: Arc[Atomic[i64]]):
    c.value.fetch_add(1)
    b.value.wait()
    c.value.fetch_add(10)
'''


def test_sync_primitives(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "true false", "true true false false", "1", "a", "b", "c", "3 true", "once", "true false true",
        "2 true", "0", "9", "33", "2 1 2 true",
    ]
