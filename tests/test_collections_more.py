"""std.collections: Deque, Heap, PriorityQueue, SortedMap, and HashMap.entry."""
from tests.helpers import run_built

SRC = """import std.collections

fn main():
    d = collections.Deque[string].new()
    for i in 0..20:
        if i % 2 == 0:
            d.push_back(f"b{i}")
        else:
            d.push_front(f"f{i}")
    print(d.len(), d.get(0), d.get(19))
    d.at(0).append_str("!")
    first = d.pop_front()
    last = d.pop_back()
    print(first, last, d.len(), d.to_list())
    nums = collections.Deque[i32].new()
    for i in 0..5:
        nums.push_back(i)
    nums.at(2) += 100
    while nums.len() > 0:
        print(nums.pop_front())

    h = collections.heap_min[i64]()
    for x in [5, 1, 9, 3, 7, 1]:
        h.push(x)
    out = List[i64]()
    while not h.is_empty():
        match h.pop():
            Valid(x): out.push(x)
            None: pass
    print(out)
    hm = collections.heap_max[string]()
    hm.push(string.from("pear"))
    hm.push(string.from("apple"))
    hm.push(string.from("zoo"))
    print(hm.peek(), hm.pop(), hm.len())

    q = collections.priority_queue[f64, string]()
    q.push(2.5, string.from("b"))
    q.push(0.5, string.from("a"))
    q.push(9.0, string.from("c"))
    print(q.peek_priority(), q.pop(), q.pop(), q.pop(), q.pop())

    m = collections.sorted_map[str, i32]()
    for w in "the quick brown fox jumps over the lazy dog the end".split(" "):
        m.entry(w, 0) += 1
    print(m.keys(), m.get("the"), m.get("cat"), m.first_key(), m.last_key())
    print(m.floor("m"), m.ceiling("m"), m.keys_between("d", "p"), m.remove("fox"), m.len())

    counts = collections.hashmap_str[i64]()
    for w in "a b a c a b".split(" "):
        counts.entry(w, 0) += 1
    print(counts.get("a"), counts.get("b"), counts.get("c"), counts.len())
"""


def test_deque_heap_priority_queue_sorted_map(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "20 f19 b18",
        'Valid("f19!") Valid("b18") 18 ["f17", "f15", "f13", "f11", "f9", "f7", "f5", "f3", "f1", "b0", "b2", "b4", '
        '"b6", "b8", "b10", "b12", "b14", "b16"]',
        "Valid(0)", "Valid(1)", "Valid(102)", "Valid(3)", "Valid(4)",
        "[1, 1, 3, 5, 7, 9]",
        'zoo Valid("zoo") 2',
        '0.5 Valid("a") Valid("b") Valid("c") None',
        '["brown", "dog", "end", "fox", "jumps", "lazy", "over", "quick", "the"] Valid(3) None Valid("brown") '
        'Valid("the")',
        'Valid("lazy") Valid("over") ["dog", "end", "fox", "jumps", "lazy", "over"] Valid(1) 8',
        "Valid(3) Valid(2) Valid(1) 3",
    ]


def test_deque_grows_and_wraps(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """import std.collections

fn main():
    d = collections.Deque[List[i32]].new()
    total: i64 = 0
    for round in 0..50:
        for i in 0..37:
            xs = List[i32]()
            xs.push(i)
            if i % 3 == 0:
                d.push_front(xs)
            else:
                d.push_back(xs)
        for _k in 0..30:
            match d.pop_front():
                Valid(xs): total += i64(xs[0])
                None: pass
    print(d.len(), total)
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.split()[0] == "350"
