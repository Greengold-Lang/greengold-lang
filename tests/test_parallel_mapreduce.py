"""std.parallel map and reduce: right answers, and the same bits whatever the number of threads.

Spec: 16
"""
from tests.helpers import run_gg_source

SRC = """import std.parallel

fn sq(x: i64) -> i64:
    return x * x

fn add(a: i64, b: i64) -> i64:
    return a + b

fn half(x: f64) -> f64:
    return x / 2.0

fn fadd(a: f64, b: f64) -> f64:
    return a + b

fn bits(x: f64) -> u64:
    v: f64 = x
    unsafe:
        return ptr_cast[*u64](addr(v))[0]

fn run(threads: usize):
    pool = parallel.Pool.new(threads)
    xs = List[i64]()
    for i in 0..20001:
        xs.push(i64(i))
    ys = List[i64]()
    for _i in 0..20001:
        ys.push(0)
    fs = List[f64]()
    for i in 0..20001:
        fs.push(1.0 / f64(i + 1))
    gs = List[f64]()
    for _i in 0..20001:
        gs.push(0.0)
    parallel.map_i64(pool, xs[..], ys[..], sq)
    parallel.map_f64(pool, fs[..], gs[..], half)
    print(ys[20000], parallel.reduce_i64(pool, ys[..], 0, add), bits(parallel.reduce_f64(pool, fs[..], 0.0, fadd)), bits(gs[7]))

fn main():
    run(1)
    run(3)
    run(8)
    empty = List[i64]()
    pool = parallel.Pool.new(2)
    print(parallel.reduce_i64(pool, empty[..], 42, add))
"""


def test_map_reduce_values_and_thread_count_independence(tmp_path):
    r = run_gg_source(tmp_path, SRC)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    n = 20000
    assert lines[0].split()[:2] == [str(n * n), str(n * (n + 1) * (2 * n + 1) // 6)]
    assert lines[0] == lines[1] == lines[2]                     # identical bits with 1, 3 and 8 threads
    assert lines[3] == "42"
