"""std.sampler."""
import math

import pytest

from .helpers import HAS_CC, run_built

pytestmark = pytest.mark.skipif(not HAS_CC, reason="no C compiler")

PROGRAM = """import std.sampler

fn make(n: usize) -> List[f32]:
    out = List[f32]()
    for i in 0..n:
        out.push(f32((i * 7) % 11) / 4.0)
    return out

fn main():
    # greedy: the largest logit (index 3 has 2.5? find it)
    logits = make(11)
    g = sampler.Sampler.new(0.0, 40, 0.9, 1)
    print(g.sample(logits[..]))
    # top_k = 1 is greedy too
    k1 = sampler.Sampler.new(1.5, 1, 1.0, 2)
    print(k1.sample(logits[..]))
    # top_p tiny keeps only the best
    tp = sampler.Sampler.new(1.0, 0, 0.0001, 3)
    print(tp.sample(logits[..]))
    # two tokens with probabilities 1/4 and 3/4
    two = List[f32]()
    two.push(0.0)
    two.push(1.0986123)
    two.push(-50.0)
    s = sampler.Sampler.new(1.0, 0, 1.0, 42)
    hits: i32 = 0
    for i in 0..4000:
        if s.sample(two[..]) == 1:
            hits += 1
    print(hits)
    # the same seed gives the same draws, another seed another ones
    a = sampler.Sampler.new(1.0, 5, 1.0, 7)
    b = sampler.Sampler.new(1.0, 5, 1.0, 7)
    c = sampler.Sampler.new(1.0, 5, 1.0, 8)
    same = true
    differ = false
    for i in 0..50:
        la = make(11)
        lb = make(11)
        lc = make(11)
        x = a.sample(la[..])
        y = b.sample(lb[..])
        z = c.sample(lc[..])
        if x != y:
            same = false
        if x != z:
            differ = true
    print(same, differ)
    # repeat penalty moves the best token away
    rp = sampler.Sampler.new(0.0, 40, 1.0, 1)
    rp.repeat_penalty = 3.0
    rp.accept(i32(3))
    l2 = make(11)
    print(l2[3] > 2.0, rp.sample(l2[..]) != 3)
"""


def test_sampler():
    res = run_built(PROGRAM, release=True, timeout=60)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.split("\n")
    logits = [((i * 7) % 11) / 4.0 for i in range(11)]
    best = max(range(11), key=lambda i: (logits[i], -i))
    assert int(lines[0]) == best
    assert int(lines[1]) == best
    assert int(lines[2]) == best
    hits = int(lines[3])
    assert 0.75 * 4000 - 4 * math.sqrt(4000 * 0.75 * 0.25) < hits < 0.75 * 4000 + 4 * math.sqrt(4000 * 0.75 * 0.25)
    assert lines[4] == "true true"
    assert lines[5] == "true true"
