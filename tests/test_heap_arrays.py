"""Arrays and slices whose elements own heap memory (`[3]string`, `[]string`)."""
from tests.helpers import front_end, run_built

ARRAYS = """\
struct Team:
    names: [2]string
    size: i32

fn count(xs: []string) -> usize:
    n: usize = 0
    for x in xs:
        n += x.len()
    return n

fn make() -> [3]string:
    return ["a", "bb", "ccc"]

fn eat(a: [2]string) -> usize:
    return a[0].len() + a[1].len()

fn main():
    arr: [3]string = ["x", "yy", "zzz"]
    print(arr, arr.len, count(arr))
    arr[1] = "replaced"
    arr[0].append_str("!")
    print(arr)
    b = make()
    c = b.clone()
    print(b == c, c[2])
    t = Team{ names: ["p", "q"], size: 2 }
    print(t, eat(t.names.clone()))
    moved = arr
    for s in moved:
        print(s)
    print(count(["a", "bcd"]))
"""

SLICES = """\
fn first(names: []string) -> str:
    return names[0].as_str()

fn shout(names: lend []string):
    for i in 0..names.len:
        names[i].append_str("!")

fn mk() -> List[string]:
    xs = List[string]()
    xs.push("m")
    return xs

fn main():
    xs = List[string]()
    xs.push("ab")
    xs.push("cde")
    print(first(xs), xs[0..1])
    shout(xs)
    part = xs[1..]
    print(part.len, part[0], first(mk()))
"""


def test_heap_arrays(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(ARRAYS)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        '["x", "yy", "zzz"] 3 6', '["x!", "replaced", "zzz"]', "true ccc",
        'Team { names: ["p", "q"], size: 2 } 2', "x!", "replaced", "zzz", "4"]


def test_heap_slices(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SLICES)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ['ab ["ab"]', "1 cde! m"]


def test_elements_are_not_moved_out_or_changed_through_read():
    _p, diags = front_end("fn f(names: []string) -> string:\n    x = names[0]\n    return x\n\n"
                          "fn g(names: []string):\n    names[0] = \"z\"\n\nfn main():\n    pass\n")
    msgs = [d.message for d in diags]
    assert any("cannot be moved out" in m for m in msgs)
    assert any("read-only slice" in m for m in msgs)
    assert all("pop()" not in d.hint for d in diags if d.hint)
