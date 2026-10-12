"""Indexing a list whose elements own heap memory (`List[List[T]]`, `List[string]`)."""
from tests.helpers import messages, run_built

PROGRAM = """\
fn total(xs: List[i32]) -> i32:
    t = 0
    for x in xs:
        t += x
    return t

fn main():
    g = List[List[i32]]()
    g.push(List[i32]())
    g.push(List[i32]())
    g[0].push(5)
    g[1].push(6)
    g[1].push(7)
    print(g[0].len, g[1][1], total(g[1]))
    names = List[string]()
    names.push(string.from("ada"))
    names.push(string.from("bob"))
    names[1].append_str("!")
    print(names[0], names[1], f"<{names[1]}>")
    names[0] = string.from("eve")
    print(names[0])
    c = names[1].clone()
    print(c)
"""


def test_heap_elements_are_places(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["1 7 13", "ada bob! <bob!>", "eve", "bob!"]
    assert "leak" not in r.stderr.lower()


def test_heap_element_cannot_be_moved_out():
    src = "fn main():\n    n = List[string]()\n    n.push(string.from(\"a\"))\n    y = n[0]\n"
    msgs = messages(src)
    assert any("cannot be moved out" in m for m in msgs)


def test_heap_element_mutation_needs_var_list():
    src = "fn main():\n    fixed n = List[List[i32]]()\n    n[0].push(1)\n"
    assert any("declared `fixed`" in m for m in messages(src))


def test_lend_element_and_read_list_conflict():
    src = ("fn f(a: lend string, b: read List[string]):\n    a.append_str(\"x\")\n\n"
           "fn main():\n    n = List[string]()\n    n.push(string.from(\"a\"))\n    f(n[0], n)\n")
    assert any("both `read` and `lend`" in m for m in messages(src))
