"""Lifetimes of views carried by value: a `str` (or a value holding one) made from a heap-owning
variable is tied to that variable, like a stored `read` reference."""
import pytest

from tests.helpers import messages, run_built

REJECTED = {
    'inner scope escape': 'fn main():\n    t = "x"\n    if true:\n        s = string.from("bb")\n        t = s.as_str()\n    print(t)\n',
    'mutate while viewed': 'fn main():\n    s = string.from("ab")\n    t = s.as_str()\n    s.append_str("c")\n    print(t)\n',
    'move while viewed': 'fn take(x: consume string):\n    print(x)\n\nfn main():\n    s = string.from("ab")\n    t = s.as_str()\n    take(s)\n    print(t)\n',
    'return view of local': 'fn f() -> str:\n    s = string.from("ab")\n    return s.as_str()\n\nfn main():\n    print(f())\n',
    'push view then drop': 'fn main():\n    names = List[str]()\n    if true:\n        s = string.from("ab")\n        names.push(s.as_str())\n    print(names.len)\n',
    'push view then mutate': 'fn main():\n    names = List[str]()\n    s = string.from("ab")\n    names.push(s.as_str())\n    s.clear()\n    print(names[0])\n',
    'reassign root while viewed': 'fn main():\n    s = string.from("ab")\n    t = s.as_str()\n    s = string.from("zz")\n    print(t)\n',
    'struct field view': 'struct P:\n    name: str\n\nfn main():\n    p = P{ name: "x" }\n    if true:\n        s = string.from("ab")\n        p = P{ name: s.as_str() }\n    print(p.name)\n',
}

ACCEPTED = {
    'literal': 'fn main():\n    t = "x"\n    if true:\n        t = "y"\n    print(t)\n',
    'view used before mutate': 'fn main():\n    s = string.from("ab")\n    t = s.as_str()\n    print(t)\n    s.append_str("c")\n    print(s)\n',
    'return view of param': 'fn f(s: string) -> str:\n    return s.as_str()\n\nfn main():\n    x = string.from("q")\n    print(f(x))\n',
    'str param passthrough': 'fn first(a: str, b: str) -> str:\n    return a\n\nfn main():\n    s = string.from("ab")\n    t = first(s.as_str(), "z")\n    print(t)\n',
    'push literal': 'fn main():\n    names = List[str]()\n    names.push("a")\n    print(names.len)\n',
    'copy len': 'fn main():\n    n: usize = 0\n    if true:\n        s = string.from("ab")\n        n = s.as_str().len\n    print(n)\n',
    'print temp': 'fn main():\n    print(string.from("ab").as_str())\n',
    'loop rebinding': 'fn main():\n    words = List[string]()\n    for w in words:\n        t = w.as_str()\n        print(t)\n',
}


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_dangling_view_is_rejected(name):
    msgs = messages(REJECTED[name])
    assert any("long enough" in m or "still tied to it" in m or "cannot be returned" in m for m in msgs), msgs


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_safe_view_is_accepted(name):
    assert messages(ACCEPTED[name]) == []


def test_copying_into_a_string_does_not_keep_the_view():
    src = """\
fn main():
    buf = string.new()
    if true:
        piece = string.from("ab")
        buf.append_str(piece.as_str())
    print(buf)
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ab"
