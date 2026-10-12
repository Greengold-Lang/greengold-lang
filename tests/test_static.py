"""`static` globals, constant data literals, and volatile memory access."""
from .helpers import messages, run_built


def test_static_counter_struct_and_table():
    src = """struct Stats:
    hits: i64

static COUNTER: i64 = 0
static STATS: Stats = Stats{ hits: 0 }
static TABLE: [4]u8 = [1, 2, 3, 4]

fn bump():
    unsafe:
        COUNTER += 1
        STATS.hits += 2

fn main():
    for i in 0..3:
        bump()
    unsafe:
        TABLE[0] = 9
        print(COUNTER, STATS.hits, TABLE[0], TABLE[3])
"""
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["3", "6", "9", "4"]


def test_static_needs_unsafe_and_plain_data():
    assert any("needs `unsafe:`" in m for m in messages("static N: i32 = 1\n\nfn main():\n    print(N)\n"))
    assert any("plain data" in m for m in messages('static S: string = "a"\n\nfn main():\n    pass\n'))


def test_const_data_literals():
    src = ("struct P:\n    x: i32\n    y: i32\n\nconst ORIGIN: P = P{ x: 1, y: 2 }\nconst PRIMES: [3]i32 = [2, 3, 5]\n\n"
           "fn main():\n    print(ORIGIN.y + PRIMES[2])\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["7"]


def test_volatile_access():
    src = ("static REG: u32 = 5\n\nfn main():\n    unsafe:\n        p = addr_mut(REG)\n"
           "        volatile_write[u32](p, volatile_read[u32](p) + 1)\n        print(volatile_read[u32](p))\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["6"]
    from greengold.cli import compile_to_ir
    assert compile_to_ir(src).count("volatile") == 3
    assert any("unsafe" in m for m in messages("fn main():\n    x: u32 = 1\n    print(volatile_read[u32](null))\n"))
