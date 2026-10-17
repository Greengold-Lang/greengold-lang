"""std.parallel: a pool of worker threads that share a range of work."""
import pytest

from .helpers import HAS_CC, run_built

PROGRAM = """import std.parallel

struct Job:
    src: []i32
    dst: *mut i32

fn square(start: usize, end: usize, ctx: *u8):
    unsafe:
        job = ptr_cast[*Job](ctx)
        for i in start..end:
            job[0].dst[i] = job[0].src[i] * job[0].src[i]

fn run(threads: usize, n: usize, chunk: usize) -> i64:
    src = List[i32]()
    dst = List[i32]()
    for i in 0..n:
        src.push(i32(i % 1000))
        dst.push(0)
    pool = parallel.Pool.new(threads)
    ss = src[..]
    ds = dst[..]
    unsafe:
        job = Job{ src: ss, dst: ptr_cast[*mut i32](addr_mut(ds)) }
        for round in 0..5:
            if chunk == 0:
                pool.for_range(n, square, ptr_cast[*u8](addr(job)))
            else:
                pool.for_range_chunked(n, chunk, square, ptr_cast[*u8](addr(job)))
    total: i64 = 0
    for i in 0..n:
        total += i64(dst[i])
    return total

fn main():
    print(run(0, 100000, 0))
    print(run(1, 100000, 0))
    print(run(4, 100000, 7))
    print(run(3, 5, 0))
    print(run(8, 0, 0))
    print(parallel.cpu_count() >= 1)
"""


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
@pytest.mark.parametrize("release", [False, True])
def test_for_range_covers_every_item_once(release):
    res = run_built(PROGRAM, release=release, timeout=60)
    assert res.returncode == 0, res.stderr
    full = sum((i % 1000) ** 2 for i in range(100000))
    small = sum((i % 1000) ** 2 for i in range(5))
    assert res.stdout.split() == [str(full), str(full), str(full), str(small), "0", "true"]
