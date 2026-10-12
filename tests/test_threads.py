"""threads, mutex, atomics, channel (std.thread)."""
import subprocess
import sys

import pytest

from tests.helpers import HAS_CC, ROOT, run_example, messages

EXPECTED = ["counter = 4000", "cas: true 7", "guarded = 8000", "received 100 sum 5050"]


def test_threads_example():
    r = run_example("threads.gg")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == EXPECTED


def test_extern_fn_pointer_param_allowed():
    msgs = messages('''
extern "pthread.h" fn pthread_create(t: *mut u64, attr: *u8, f: fn(*u8) -> *u8, arg: *u8) -> i32

fn main():
    print(1)
''')
    assert not msgs


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_safe_thread_spawn_and_methods(tmp_path):
    from tests.helpers import run_gg_source
    src = """import std.thread

fn worker():
    print("hello from safe thread")

fn main():
    t = thread.Thread.spawn(worker)
    t.join()

    counter = thread.AtomicI64.new(10)
    counter.fetch_and_add(5)
    print("atomic =", counter.load())
    counter.compare_and_swap(15, 100)
    print("after cas =", counter.load())

    lock = thread.Mutex.new()
    lock.lock()
    print("locked")
    lock.unlock()
    print("unlocked")

    ch = thread.Channel.new()
    ch.send(42)
    ch.send(99)
    if let Valid(v1) = ch.recv():
        print("chan1 =", v1)
    if let Valid(v2) = ch.recv():
        print("chan2 =", v2)
    ch.close()
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines == [
        "hello from safe thread",
        "atomic = 15",
        "after cas = 100",
        "locked",
        "unlocked",
        "chan1 = 42",
        "chan2 = 99",
    ]


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_safe_thread_spawn_arg(tmp_path):
    from tests.helpers import run_gg_source
    src = """import std.thread

fn worker_arg(id: i64):
    print("worker received:", id)

fn main():
    t1 = thread.Thread.spawn_with_param(worker_arg, 100)
    t2 = thread.Thread.spawn_with_param(worker_arg, 200)
    t1.join()
    t2.join()
    print("both joined")
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert "both joined" in r.stdout
    assert "worker received: 100" in r.stdout
    assert "worker received: 200" in r.stdout


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_descriptive_thread_and_channel_api(tmp_path):
    from tests.helpers import run_gg_source
    src = """import std.thread

fn worker(val: i64):
    print("running with:", val)

fn main():
    t = thread.Thread.spawn_with_param(worker, 999)
    t.join()
    thread.Thread.yield_now()

    ch = thread.Channel.new()
    ch.send(77)
    if let Valid(x) = ch.recv():
        print("received:", x)
    ch.close()

    a = thread.AtomicI64.new(50)
    a.fetch_and_add(5)
    swapped = a.compare_and_swap(55, 100)
    print("cas:", swapped, a.load())
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines == [
        "running with: 999",
        "received: 77",
        "cas: true 100",
    ]


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_descriptive_core_and_pointer_api(tmp_path):
    from tests.helpers import run_gg_source
    src = """fn main():
    opt = Valid(42)
    print("has_value:", opt.has_value())
    print("value_or:", opt.value_or(0))
    print("value_or_panic:", opt.value_or_panic())

    s = string.from("Greengold")
    s.append_str(" Language")
    print("string:", s.as_str())

    num = 123
    unsafe:
        p = address_of_mut(num)
        raw = pointer_cast[*mut u8](p)
        off = pointer_offset(raw, 0)
        addr_val = pointer_to_int(off)
        back = int_to_pointer[*mut i32](addr_val)
        print("pointer back:", back[0])
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines == [
        "has_value: true",
        "value_or: 42",
        "value_or_panic: 42",
        "string: Greengold Language",
        "pointer back: 123",
    ]




# -- OS handles are moved, never copied (GG0323) ---------------------------------------------

def _check_json(tmp_path, src):
    import json
    f = tmp_path / "a.gg"
    f.write_text(src, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "greengold", "check", "--json", str(f)],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)
    return json.loads(r.stdout)["diagnostics"]


def test_handle_assignment_moves(tmp_path):
    diags = _check_json(tmp_path, """import std.thread

fn main():
    m = thread.Mutex.new()
    n = m
    n.lock()
    m.lock()
""")
    assert [d["code"] for d in diags] == ["GG0301"]
    # a clone would be a second, unrelated lock: no `.clone()` fix is offered
    assert all(".clone()" not in f["description"] for f in diags[0]["fixes"])


def test_channel_copy_is_rejected(tmp_path):
    diags = _check_json(tmp_path, """import std.thread

fn main():
    c = thread.Channel.new()
    d = c
    c.send(1)
    print(d.recv().value_or(0))
""")
    assert [d["code"] for d in diags] == ["GG0301"]


def test_handle_clone_and_copy_are_rejected(tmp_path):
    diags = _check_json(tmp_path, """import std.thread

struct Guarded:
    lock: thread.Mutex
    n: i32

fn main():
    m = thread.Mutex.new()
    a = m.clone()
    b = copy m
    g = Guarded{ lock: thread.Mutex.new(), n: 1 }
    h = g.clone()
""")
    assert [d["code"] for d in diags] == ["GG0323", "GG0323", "GG0323"]
    assert diags[2]["details"]["handle"] == "thread::Mutex"


def test_struct_holding_a_handle_moves(tmp_path):
    diags = _check_json(tmp_path, """import std.thread

struct Guarded:
    lock: thread.Mutex
    n: i32

fn main():
    g = Guarded{ lock: thread.Mutex.new(), n: 1 }
    h = g
    print(g.n)
""")
    assert [d["code"] for d in diags] == ["GG0301"]
    assert all(".clone()" not in f["description"] for f in diags[0]["fixes"])


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_handles_in_lists_params_and_returns(tmp_path):
    from tests.helpers import run_gg_source
    src = """import std.thread

fn worker():
    print("w")

fn make() -> thread.Mutex:
    m = thread.Mutex.new()
    return m

fn use_lock(m: thread.Mutex):
    m.lock()
    m.unlock()

fn main():
    m = make()
    use_lock(m)
    use_lock(m)
    locks = List[thread.Mutex]()
    locks.push(thread.Mutex.new())
    locks[0].lock()
    locks[0].unlock()
    ts = List[thread.Thread]()
    ts.push(thread.Thread.spawn(worker))
    ts[0].join()
    print("done")
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["w", "done"]


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_second_join_panics(tmp_path):
    from tests.helpers import run_gg_source
    src = """import std.thread

fn worker():
    print("w")

fn main():
    t = thread.Thread.spawn(worker)
    t.join()
    t.join()
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode != 0
    assert "already joined" in r.stdout + r.stderr
