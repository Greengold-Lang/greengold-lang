"""std.nn: transformer kernels checked against plain Python."""
import math
import struct

import pytest

from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def vec(n: int, a: int, b: int, m: int = 101) -> list[float]:
    """The same values as the Greengold helper `vec`."""
    return [f32(((i * a + b) % m) / 50.0 - 1.0) for i in range(n)]


PROGRAM = """import std.nn
import std.parallel

fn vec(n: usize, a: usize, b: usize) -> List[f32]:
    out = List[f32]()
    for i in 0..n:
        out.push(f32((i * a + b) % 101) / 50.0 - 1.0)
    return out

fn show(name: str, xs: []f32):
    print("#", name)
    for i in 0..xs.len:
        print(f64(xs[i]))

fn zeros(n: usize) -> List[f32]:
    out = List[f32]()
    for i in 0..n:
        out.push(0.0)
    return out

fn main():
    # exp
    grid = List[f32]()
    for i in 0..41:
        grid.push(f32(i) * 4.5 - 90.0)
    ex = List[f32]()
    for i in 0..grid.len():
        ex.push(nn.exp(grid[i]))
    show("exp", ex[..])
    # softmax of several lengths
    sizes: [6]usize = [1, 5, 8, 13, 16, 37]
    for n in sizes:
        x = vec(n, 37, 11)
        nn.softmax(x[..])
        show("softmax", x[..])
    # rmsnorm
    x = vec(21, 13, 5)
    w = vec(21, 7, 3)
    out = zeros(21)
    nn.rmsnorm(x[..], w[..], 0.00001, out[..])
    show("rmsnorm", out[..])
    # silu and swiglu
    s = vec(19, 29, 2)
    for i in 0..s.len():
        s[i] = s[i] * 6.0
    u = vec(19, 3, 9)
    g = s.clone()
    nn.silu(s[..])
    show("silu", s[..])
    nn.swiglu(g[..], u[..])
    show("swiglu", g[..])
    # rope, both layouts
    q = vec(24, 17, 4)
    nn.rope(q[..], 3, 8, 5, 10000.0, false)
    show("rope", q[..])
    k = vec(24, 17, 4)
    nn.rope(k[..], 3, 8, 7, 500.0, true)
    show("rope_neox", k[..])
    # dot, axpy, add, matvec
    a = vec(37, 5, 1)
    b = vec(37, 11, 8)
    print("#", "dot")
    print(f64(nn.dot(a[..], b[..])))
    nn.axpy(0.5, a[..], b[..])
    show("axpy", b[..])
    nn.add(b[..], a[..])
    show("add", b[..])
    mat = vec(5 * 21, 3, 7)
    xv = vec(21, 9, 1)
    y = zeros(5)
    nn.matvec(mat[..], 5, 21, xv[..], y[..])
    show("matvec", y[..])
    # attention: 4 query heads over 2 key/value heads, head size 8, 5 tokens
    cache = nn.KvCache.new(2, 8, 16)
    tokens: usize = 5
    for t in 0..tokens:
        kt = vec(16, 7 + t, 3 * t)
        vt = vec(16, 5, 2 * t + 1)
        cache.append(kt[..], vt[..])
    qa = vec(32, 11, 6)
    oa = zeros(32)
    nn.attention(qa[..], cache, 4, oa[..])
    show("attention", oa[..])
    ob = zeros(32)
    pool = parallel.Pool.new(3)
    nn.attention_parallel(pool, qa[..], cache, 4, ob[..])
    show("attention_parallel", ob[..])
    # a batch of 3 tokens (positions 2, 3, 4) in one go equals three single calls over growing prefixes
    qb = vec(96, 3, 8)
    ofull = zeros(96)
    nn.attention_batch_parallel(pool, qb[..], cache, 4, 2, 3, ofull[..])
    show("batch_attention", ofull[..])
    three: usize = 3
    for t in 0..three:
        qt = qb[t * 32..(t + 1) * 32]
        one = zeros(32)
        nn.attention_prefix(qt, cache, 4, 2 + t + 1, one[..])
        show("prefix_attention", one[..])
    cache.truncate(2)
    print("#", "len")
    print(cache.len())
"""


def sections(text: str) -> dict[str, list[list[float]]]:
    out: dict[str, list[list[float]]] = {}
    for line in text.splitlines():
        if line.startswith("# "):
            cur: list[float] = []
            out.setdefault(line[2:], []).append(cur)
        else:
            cur.append(float(line))
    return out


def close(got, want, rel=2e-5, abs_=2e-6):
    assert len(got) == len(want), (len(got), len(want))
    for g, w in zip(got, want):
        assert g == pytest.approx(w, rel=rel, abs=abs_), (got, want)


@pytest.fixture(scope="module")
def result():
    res = run_built(PROGRAM, release=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return sections(res.stdout)


def test_exp(result):
    grid = [i * 4.5 - 90.0 for i in range(41)]
    want = [math.exp(min(max(x, f32(-87.3)), f32(88.3))) for x in grid]
    close(result["exp"][0], want, rel=3e-6, abs_=0.0)


def test_softmax(result):
    for n, got in zip([1, 5, 8, 13, 16, 37], result["softmax"]):
        x = vec(n, 37, 11)
        top = max(x)
        e = [math.exp(v - top) for v in x]
        close(got, [v / sum(e) for v in e])


def test_rmsnorm(result):
    x, w = vec(21, 13, 5), vec(21, 7, 3)
    scale = 1.0 / math.sqrt(sum(v * v for v in x) / 21 + 1e-5)
    close(result["rmsnorm"][0], [a * scale * b for a, b in zip(x, w)])


def test_silu_swiglu(result):
    s = [f32(v * 6.0) for v in vec(19, 29, 2)]
    u = vec(19, 3, 9)
    silu = [v / (1 + math.exp(-v)) for v in s]
    close(result["silu"][0], silu)
    close(result["swiglu"][0], [a * b for a, b in zip(silu, u)])


def rope_ref(x, n_heads, head_dim, pos, base, neox):
    x = list(x)
    half = head_dim // 2
    for i in range(half):
        angle = pos * base ** (-2.0 * i / head_dim)
        c, s = math.cos(angle), math.sin(angle)
        for h in range(n_heads):
            a = h * head_dim + (i if neox else 2 * i)
            b = a + half if neox else a + 1
            x[a], x[b] = x[a] * c - x[b] * s, x[a] * s + x[b] * c
    return x


def test_rope(result):
    close(result["rope"][0], rope_ref(vec(24, 17, 4), 3, 8, 5, 10000.0, False))
    close(result["rope_neox"][0], rope_ref(vec(24, 17, 4), 3, 8, 7, 500.0, True))


def test_dot_axpy_add_matvec(result):
    a, b = vec(37, 5, 1), vec(37, 11, 8)
    close(result["dot"][0], [sum(x * y for x, y in zip(a, b))])
    axpy = [y + 0.5 * x for x, y in zip(a, b)]
    close(result["axpy"][0], axpy)
    close(result["add"][0], [x + y for x, y in zip(axpy, a)])
    mat, xv = vec(105, 3, 7), vec(21, 9, 1)
    close(result["matvec"][0], [sum(mat[r * 21 + c] * xv[c] for c in range(21)) for r in range(5)])


def test_attention(result):
    n_heads, n_kv, hd, tokens = 4, 2, 8, 5
    keys = [vec(16, 7 + t, 3 * t) for t in range(tokens)]
    values = [vec(16, 5, 2 * t + 1) for t in range(tokens)]
    q = vec(32, 11, 6)
    want = []
    for h in range(n_heads):
        g = h // (n_heads // n_kv)
        qh = q[h * hd:(h + 1) * hd]
        scores = [sum(a * b for a, b in zip(qh, keys[t][g * hd:(g + 1) * hd])) / math.sqrt(hd) for t in range(tokens)]
        top = max(scores)
        e = [math.exp(s - top) for s in scores]
        p = [v / sum(e) for v in e]
        want += [sum(p[t] * values[t][g * hd + i] for t in range(tokens)) for i in range(hd)]
    close(result["attention"][0], want)
    assert result["attention_parallel"][0] == result["attention"][0]
    assert result["batch_attention"][0] == sum(result["prefix_attention"], [])
    assert result["len"][0] == [2.0]


def test_lend_slice_first_used_in_a_branch():
    """A `lend` slice parameter whose first use is inside an `if` must still be usable after it."""
    res = run_built("""fn fill(x: lend []f32, flag: bool):
    if flag:
        x[0] = 1.0
    x[1] = 2.0
    i: usize = 2
    while i < x.len:
        x[i] = x[i - 1] + 1.0
        i += 1

fn main():
    xs: [5]f32 = [0.0; 5]
    fill(xs, true)
    print(xs)
""", release=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["[1,", "2,", "3,", "4,", "5]"]
