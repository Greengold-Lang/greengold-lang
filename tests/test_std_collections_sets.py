"""std.collections SortedSet / BitSet and the stable sort in std.sort."""
from tests.helpers import run_gg_source

PROGRAM = r'''import std.collections { sorted_set, bitset_new }
import std.sort

struct Rec:
    key: i32
    tag: i32

fn by_key(a: Rec, b: Rec) -> bool:
    return a.key < b.key

fn main():
    s = sorted_set[i32]()
    print(s.insert(5), s.insert(1), s.insert(9), s.insert(5), s.len())
    print(s.floor(6).value_or(-1), s.ceiling(6).value_or(-1), s.first().value_or(-1), s.remove(1), s.contains(1))
    print(s.between(2, 10).len, s.to_list().len)
    b = bitset_new()
    b.insert(3)
    b.insert(200)
    b.insert(64)
    c = bitset_new()
    c.insert(64)
    c.insert(7)
    print(b.count(), b.contains(200), b.contains(199), b.next_from(4).value_or(0), b.remove(3), b.insert(64))
    b.intersect_with(c)
    print(b.to_list().len, b.to_list()[0])
    c.union_with(b)
    c.subtract(b)
    print(c.to_list().len, c.to_list()[0])
    v = List[Rec]()
    for i in 0..40:
        v.push(Rec{ key: i32(i % 3), tag: i32(i) })
    sort.sort_stable_by(v, by_key)
    ok = true
    for i in 1..v.len:
        if v[i].key < v[i - 1].key or (v[i].key == v[i - 1].key and v[i].tag < v[i - 1].tag):
            ok = false
    print(ok, v[0].tag, v[39].tag, sort.is_sorted(List[i32]()))
    nums = List[i64]()
    for i in 0..100:
        nums.push(i64((i * 37) % 101))
    sort.sort_stable(nums)
    print(sort.is_sorted(nums), nums[0], nums[99])
'''


def test_sorted_set_bitset_stable_sort(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "true true true false 3", "5 9 1 true false", "2 2", "3 true false 64 true false", "1 64", "1 7",
        "true 0 38 true", "true 0 100",
    ]
